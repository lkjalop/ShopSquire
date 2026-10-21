import asyncio

from starlette.requests import Request

from src.app.routers.chat import _call_recommend_in_process, _effective_chat_query
from src.app.services.recommendation_delegation_policy import v2_only_unavailable_response
from src.app.services.recommendation_facade import FacadeOutcome


def _request() -> Request:
    return Request({
        "type": "http",
        "method": "POST",
        "path": "/api/v1/chat/query",
        "headers": [
            (b"x-api-key", b"local-merchant-key"),
            (b"x-tenant-id", b"tenant-a"),
        ],
        "client": ("127.0.0.1", 1234),
        "server": ("127.0.0.1", 8080),
        "scheme": "http",
        "query_string": b"",
    })


def test_in_process_recommend_preserves_typed_facade_dependencies(monkeypatch):
    captured = {}
    dispatches = []
    def facade(db, redis, **kwargs):
        captured.update(db=db, redis=redis, **kwargs)
        return FacadeOutcome(status="served", payload={"requested_quantity": 20}, lane="PROCUREMENT")
    monkeypatch.setattr("src.app.services.recommendation_facade.dispatch_recommendation_core_typed", facade)
    monkeypatch.setattr("src.app.observability.metrics.record_recommendation_dispatch", lambda **fields: dispatches.append(fields))
    monkeypatch.setattr("src.app.services.recommendation_compatibility.serve_v2_compatibility",
                        lambda **_: (_ for _ in ()).throw(AssertionError('single facade must not retry compatibility')))
    redis, db = object(), object()
    request = _request()
    from types import SimpleNamespace
    request.state.operator_identity = SimpleNamespace(tenant_id="tenant-a")
    status, body = asyncio.run(_call_recommend_in_process(
        request, {"uid":"buyer-1", "query":"quote 20 laptops", "budget_max":55000,
                     "turn_intent":"PROCUREMENT", "external_research_consent":"true"},
        redis=redis, db=db, role="merchant"))
    assert status == 200 and body["execution_mode"] == "v2_served"
    assert body["requested_quantity"] == 20
    assert captured["db"] is db and captured["redis"] is redis
    assert captured["tenant_id"] == "tenant-a" and captured["uid"] == "buyer-1"
    assert captured["external_research_consent"] is True
    assert captured["intent_hint"] == "PROCUREMENT" and captured["budget_max"] == 55000
    assert captured["role"] == "merchant"
    assert captured["source_ip"] == '127.0.0.1'
    assert dispatches == [{'outcome': 'v2_served', 'lane': 'PROCUREMENT', 'reason': 'served'}]


def test_in_process_recommend_returns_typed_facade_service_without_compatibility(monkeypatch):
    payload = {"results": [{"sku": "V2-1"}], "decision_trace_id": "trace-1"}
    dispatches = []
    monkeypatch.setattr(
        "src.app.services.recommendation_facade.dispatch_recommendation_core_typed",
        lambda *_args, **_kwargs: FacadeOutcome(
            status="served", payload=payload, lane="SEARCH"),
    )
    monkeypatch.setattr(
        "src.app.services.recommendation_compatibility.serve_v2_compatibility",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("compatibility cutover must not run")
        ),
    )
    monkeypatch.setattr(
        "src.app.observability.metrics.record_recommendation_dispatch",
        lambda **fields: dispatches.append(fields),
    )

    status, body = asyncio.run(_call_recommend_in_process(
        _request(), {"uid": "buyer-1", "query": "gaming laptop", "trace_id": "trace-1"},
        redis=object(), db=object(), role="merchant"))

    assert status == 200
    assert body["results"] == payload["results"]
    assert body["decision_trace_id"] == "trace-1"
    assert body["execution_mode"] == "v2_served"
    assert body["execution_lane"] == "SEARCH"
    assert dispatches == [{
        "outcome": "v2_served",
        "lane": "SEARCH",
        "reason": "served",
    }]


def test_v2_only_pilot_never_invokes_compatibility_cutover(monkeypatch):
    dispatches = []
    monkeypatch.setenv("RECOMMEND_COMPATIBILITY_CUTOVER_ENABLED", "0")
    monkeypatch.setattr(
        "src.app.services.recommendation_facade.dispatch_recommendation_core_typed",
        lambda *_args, **_kwargs: FacadeOutcome(
            status="delegate", reason="lane_not_enrolled", lane="SUPPORT_CLAIM",
        ),
    )
    monkeypatch.setattr(
        "src.app.observability.metrics.record_recommendation_dispatch",
        lambda **fields: dispatches.append(fields),
    )

    status, body = asyncio.run(_call_recommend_in_process(
        _request(),
        {"uid": "buyer-1", "query": "help with a damaged order", "trace_id": "trace-v2-only"},
        redis=object(), db=object(), role="merchant",
    ))

    assert status == 200
    assert body["execution_mode"] == "v2_unavailable"
    assert body["execution_lane"] == "SUPPORT_CLAIM"
    assert body["products"] == []
    assert body["action_executed"] is False
    assert body["semantic_resolution"]["catalog_authority"] == "blocked"
    assert body["execution_state_envelope"]["catalog_authority"] == "blocked"
    assert body["execution_state_envelope"]["commerce_authority"] == "none"
    assert body["execution_state_envelope"]["research_authority"] == "required"
    assert dispatches == [{
        "outcome": "v2_unavailable",
        "lane": "SUPPORT_CLAIM",
        "reason": "lane_not_enrolled",
    }]


def test_v2_deadline_fails_closed_with_revision_safe_authority_envelope():
    body = v2_only_unavailable_response(
        status="degraded",
        reason="request_cancelled:request_deadline_exceeded",
        lane="SEARCH",
        trace_id="future-game-timeout",
        query="I want to play an unreleased game",
        external_research_authorized=True,
    )

    envelope = body["execution_state_envelope"]
    assert envelope["model_status"] == "timeout"
    assert envelope["research_authority"] == "granted"
    assert envelope["provider_status"] == "not_attempted"
    assert envelope["catalog_authority"] == "blocked"
    assert envelope["commerce_authority"] == "none"
    assert body["semantic_resolution"]["catalog_authority"] == "blocked"
    assert body["products"] == []
    assert body["action_executed"] is False


def test_typed_facade_failure_is_observable(monkeypatch):
    dispatches = []
    def fail(*args, **kwargs):
        raise RuntimeError("facade failed")
    monkeypatch.setattr("src.app.services.recommendation_facade.dispatch_recommendation_core_typed", fail)
    monkeypatch.setattr("src.app.observability.metrics.record_recommendation_dispatch", lambda **fields: dispatches.append(fields))
    import pytest
    with pytest.raises(RuntimeError, match="facade failed"):
        asyncio.run(_call_recommend_in_process(
            _request(), {"uid":"buyer-1", "query":"gaming laptop"},
            redis=object(), db=object(), role="merchant"))
    assert dispatches == [{'outcome': 'error', 'lane': None, 'reason': 'core_error'}]


def test_typed_and_spoken_input_share_one_semantic_dispatch_contract(monkeypatch):
    typed_query, typed_voice, _ = _effective_chat_query({
        "query": "compare Dell G16 and Lenovo Legion",
    })
    spoken_query, spoken_voice, confidence = _effective_chat_query({
        "voice_transcript": "compare Dell G16 and Lenovo Legion",
        "voice_confidence": 0.94,
    })
    assert typed_query == spoken_query
    assert typed_voice is False
    assert spoken_voice is True
    assert confidence == 0.94

    def fake_facade(*_args, **kwargs):
        assert kwargs["query"] == typed_query
        return FacadeOutcome(
            status="served",
            lane="COMPARE",
            payload={
                "trace_id": kwargs["trace_id"],
                "decision_trace_id": kwargs["trace_id"],
                "turn_intent": "COMPARE",
                "constraints_used": {"named_products": ["Dell G16", "Lenovo Legion"]},
                "results": [{"sku": "DELL-G16"}, {"sku": "LENOVO-LEGION"}],
                "canonical_identity": {
                    "trace_id": kwargs["trace_id"],
                    "ordered_skus": ["DELL-G16", "LENOVO-LEGION"],
                },
            },
        )

    monkeypatch.setattr(
        "src.app.services.recommendation_facade.dispatch_recommendation_core_typed",
        fake_facade,
    )
    outputs = []
    for query in (typed_query, spoken_query):
        status, body = asyncio.run(_call_recommend_in_process(
            _request(),
            {"uid": "buyer-1", "query": query, "trace_id": "trace-parity"},
            redis=object(), db=object(), role="merchant",
        ))
        assert status == 200
        outputs.append(body)

    for key in (
        "turn_intent", "constraints_used", "results",
        "trace_id", "decision_trace_id", "canonical_identity",
    ):
        assert outputs[0][key] == outputs[1][key]
