import asyncio

from starlette.requests import Request

from src.app.routers.chat import _call_recommend_in_process, _effective_chat_query
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


def test_in_process_recommend_preserves_request_and_dependencies(monkeypatch):
    captured = {}
    dispatches = []

    def fake_suggest(**kwargs):
        captured.update(kwargs)
        return {"results": [{"sku": "LAP-1"}], "requested_quantity": 20}

    monkeypatch.setattr("src.app.routers.recommend.suggest", fake_suggest)
    monkeypatch.setattr(
        "src.app.observability.metrics.record_recommendation_dispatch",
        lambda **fields: dispatches.append(fields),
    )
    redis = object()
    db = object()
    status, body = asyncio.run(_call_recommend_in_process(
        _request(),
        {
            "uid": "buyer-1",
            "query": "quote 20 laptops",
            "budget_max": 55000,
            "turn_intent": "PROCUREMENT",
            "external_research_consent": "true",
        },
        redis=redis,
        db=db,
        role="merchant",
    ))

    assert status == 200
    assert body["requested_quantity"] == 20
    assert body["execution_mode"] == "legacy_delegated"
    assert captured["uid"] == "buyer-1"
    assert captured["turn_intent"] == "PROCUREMENT"
    assert captured["request"].headers["x-tenant-id"] == "tenant-a"
    assert captured["redis"] is redis
    assert captured["db"] is db
    assert captured["role"] == "merchant"
    assert captured["external_research_consent"] is True
    assert dispatches == [{
        "outcome": "legacy_delegated",
        "lane": "PROCUREMENT",
        "reason": "mode_off",
    }]


def test_in_process_recommend_returns_typed_facade_service_without_legacy(monkeypatch):
    payload = {"results": [{"sku": "V2-1"}], "decision_trace_id": "trace-1"}
    dispatches = []
    monkeypatch.setattr(
        "src.app.services.recommendation_facade.dispatch_recommendation_core_typed",
        lambda *_args, **_kwargs: FacadeOutcome(
            status="served", payload=payload, lane="SEARCH"),
    )
    monkeypatch.setattr(
        "src.app.routers.recommend.suggest",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("legacy must not run")),
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


def test_v2_only_pilot_never_invokes_legacy_delegate(monkeypatch):
    dispatches = []
    monkeypatch.setenv("RECOMMEND_LEGACY_DELEGATE_ENABLED", "0")
    monkeypatch.setattr(
        "src.app.services.recommendation_facade.dispatch_recommendation_core_typed",
        lambda *_args, **_kwargs: FacadeOutcome(
            status="delegate", reason="lane_not_enrolled", lane="SUPPORT_CLAIM",
        ),
    )
    monkeypatch.setattr(
        "src.app.services.legacy_recommendation_delegate.delegate_legacy_recommendation",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("strict V2 pilot must not invoke legacy")
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
    assert dispatches == [{
        "outcome": "v2_unavailable",
        "lane": "SUPPORT_CLAIM",
        "reason": "lane_not_enrolled",
    }]


def test_legacy_delegate_failure_is_observable(monkeypatch):
    dispatches = []
    monkeypatch.setattr(
        "src.app.services.recommendation_facade.dispatch_recommendation_core_typed",
        lambda *_args, **_kwargs: FacadeOutcome(
            status="delegate", reason="outside_pilot_cohort", lane="SEARCH",
        ),
    )
    monkeypatch.setattr(
        "src.app.services.legacy_recommendation_delegate.delegate_legacy_recommendation",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("legacy failed")),
    )
    monkeypatch.setattr(
        "src.app.observability.metrics.record_recommendation_dispatch",
        lambda **fields: dispatches.append(fields),
    )

    try:
        asyncio.run(_call_recommend_in_process(
            _request(), {"uid": "buyer-1", "query": "gaming laptop"},
            redis=object(), db=object(), role="merchant",
        ))
    except RuntimeError as exc:
        assert str(exc) == "legacy failed"
    else:
        raise AssertionError("delegate failure must propagate to the chat error boundary")

    assert dispatches == [{
        "outcome": "error",
        "lane": "SEARCH",
        "reason": "outside_pilot_cohort",
    }]


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
