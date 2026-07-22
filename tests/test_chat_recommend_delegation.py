import asyncio

from starlette.requests import Request

from src.app.routers.chat import _call_recommend_in_process
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

    def fake_suggest(**kwargs):
        captured.update(kwargs)
        return {"results": [{"sku": "LAP-1"}], "requested_quantity": 20}

    monkeypatch.setattr("src.app.routers.recommend.suggest", fake_suggest)
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
    assert captured["uid"] == "buyer-1"
    assert captured["turn_intent"] == "PROCUREMENT"
    assert captured["request"].headers["x-tenant-id"] == "tenant-a"
    assert captured["redis"] is redis
    assert captured["db"] is db
    assert captured["role"] == "merchant"
    assert captured["external_research_consent"] is True


def test_in_process_recommend_returns_typed_facade_service_without_legacy(monkeypatch):
    payload = {"results": [{"sku": "V2-1"}], "decision_trace_id": "trace-1"}
    monkeypatch.setattr(
        "src.app.services.recommendation_facade.dispatch_recommendation_core_typed",
        lambda *_args, **_kwargs: FacadeOutcome(
            status="served", payload=payload, lane="SEARCH"),
    )
    monkeypatch.setattr(
        "src.app.routers.recommend.suggest",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("legacy must not run")),
    )

    status, body = asyncio.run(_call_recommend_in_process(
        _request(), {"uid": "buyer-1", "query": "gaming laptop", "trace_id": "trace-1"},
        redis=object(), db=object(), role="merchant"))

    assert status == 200
    assert body == payload
