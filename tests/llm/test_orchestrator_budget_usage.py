import os
import pytest

from src.app.services import llm as llm_mod


class FakeBudget:
    def __init__(self, *_args, **_kwargs):
        self.enabled = True
        self.calls = {
            "check": [],
            "record": [],
        }

    def check_budget(self, uid: str, tier: str, estimated_tokens: int):
        self.calls["check"].append({"uid": uid, "tier": tier, "estimated_tokens": estimated_tokens})
        return True, "ok", {"tokens_remaining": 999999, "cost_remaining_usd": 999999.0}

    def record_usage(self, uid: str, tokens: int, cost: float):
        self.calls["record"].append({"uid": uid, "tokens": tokens, "cost": cost})


class FakeLLMResult:
    def __init__(self, ranked):
        self.output = {"ranked": ranked}
        self.tokens_prompt = 123
        self.tokens_completion = 45
        self.duration_seconds = 0.01


def test_orchestrator_rerank_records_budget(monkeypatch):
    # Ensure provider settings are sane (but we'll bypass via monkeypatch)
    os.environ["LLM_PROVIDER"] = "ollama"
    os.environ["LLM_MODEL"] = "llama3:8b"

    # Monkeypatch TokenBudget used inside llm module
    monkeypatch.setattr(llm_mod, "TokenBudget", FakeBudget)

    # Monkeypatch LLMProviderClient.rerank to return a controlled result
    def fake_rerank(self, candidates, constraints):
        ranked = [candidates[2], candidates[0], candidates[1]]  # some order
        return FakeLLMResult(ranked)

    monkeypatch.setattr(llm_mod.LLMProviderClient, "rerank", fake_rerank, raising=True)

    orch = llm_mod.LLMOrchestrator()
    uid = "guest-123"
    candidates = [
        {"sku": "aa", "name": "BrandX Laptop", "price_cents": 90000, "stock": 10},
        {"sku": "bb", "name": "BrandY Ultrabook", "price_cents": 120000, "stock": 0},
        {"sku": "cc", "name": "Generic Laptop", "price_cents": 80000, "stock": 5},
    ]
    constraints = {"budget_max": 100000, "brands": ["brandx"]}

    ranked = orch.rerank_with_budget(uid, candidates, constraints)

    # Verify ordering matches fake_rerank result
    assert [c["sku"] for c in ranked] == ["cc", "aa", "bb"]

    # Verify budget recorded usage using tokens from FakeLLMResult
    # Retrieve the FakeBudget instance from orchestrator
    fb = orch.budget
    assert isinstance(fb, FakeBudget)
    assert len(fb.calls["check"]) == 1
    assert len(fb.calls["record"]) == 1
    rec = fb.calls["record"][0]
    assert rec["uid"] == uid
    assert rec["tokens"] == 123 + 45
    assert rec["cost"] == 0.0
