from __future__ import annotations

import time


def test_mock_runtime_never_calls_router_transport(monkeypatch) -> None:
    from src.app.services.recommendation_core import turn_router

    monkeypatch.delenv("ROUTER_MODEL_ENABLED", raising=False)
    monkeypatch.setenv("USE_MOCK_LLM", "1")
    started = time.monotonic()

    assert turn_router._default_llm_fn("classify", 12.0) == ""
    assert time.monotonic() - started < 0.1
    metrics = turn_router.last_router_call_metrics()
    assert metrics["provider"] == "mock"
    assert metrics["outcome"] == "mock_disabled"


def test_mock_runtime_never_calls_cart_resolver_transport(monkeypatch) -> None:
    from src.app.services.recommendation_core import cart_resolver

    monkeypatch.delenv("CART_RESOLVER_MODEL_ENABLED", raising=False)
    monkeypatch.setenv("USE_MOCK_LLM", "1")

    assert cart_resolver._default_llm_fn("resolve", 12.0) == ""
