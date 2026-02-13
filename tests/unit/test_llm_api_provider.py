import json

import pytest

from src.app.services.llm import LLMOrchestrator, LLMProviderClient, TokenBudget


def test_rerank_with_budget_records_usage(monkeypatch):
    # Capture record_usage calls
    recorded = []

    # Prevent TokenBudget from attempting real redis connections
    monkeypatch.setattr(TokenBudget, "__init__", lambda self, r: None)

    def fake_check(self, uid, tier, estimated_tokens):
        return True, "ok", 100000

    def fake_record(self, uid, tokens, cost):
        recorded.append((uid, tokens, cost))

    monkeypatch.setattr(TokenBudget, "check_budget", fake_check)
    monkeypatch.setattr(TokenBudget, "record_usage", fake_record)

    # Monkeypatch provider API call to return deterministic JSON
    def fake_api_call(self, prompt_obj, system=None, uid=None):
        return json.dumps({"ranked_skus": ["sku1", "sku2"], "rationale": "test"})

    monkeypatch.setattr(LLMProviderClient, "_call_api_provider", fake_api_call)

    orchestrator = LLMOrchestrator()

    candidates = [
        {"sku": "sku1", "name": "One", "price_cents": 1000, "stock": 5},
        {"sku": "sku2", "name": "Two", "price_cents": 2000, "stock": 2},
    ]
    constraints = {}
    uid = "test-user"

    out = orchestrator.rerank_with_budget(uid, candidates, constraints)

    # Ensure we got reordered candidates list (from fake ranked skus)
    assert isinstance(out, list)
    assert len(out) == 2
    assert out[0]["sku"] == "sku1"

    # Ensure record_usage was invoked at least once
    assert len(recorded) >= 1
    assert recorded[0][0] == uid
