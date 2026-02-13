import os

from src.app.services.llm import LLMOrchestrator, LLMProviderClient, LLMResult, TokenBudget


def test_rerank_tiered_provider_fallback(monkeypatch):
    os.environ["LLM_PROVIDER_FALLBACK_STANDARD"] = "openai,ollama"
    os.environ["LLM_PROVIDER_TIER_STANDARD"] = "openai"
    os.environ["LLM_MODEL_TIER_STANDARD"] = "gpt-4o-mini"

    monkeypatch.setattr(TokenBudget, "__init__", lambda self, r: None)
    monkeypatch.setattr(TokenBudget, "check_budget", lambda self, uid, tier, estimated_tokens: (True, "ok", 10000))
    monkeypatch.setattr(TokenBudget, "record_usage", lambda self, uid, tokens, cost: None)

    calls = []

    def fake_once(self, candidates, constraints, uid=None, provider=None, model=None, allow_stub_fallback=False, trace_id=None, **kwargs):
        calls.append((provider, model))
        if provider == "openai":
            return None
        return LLMResult(output={"ranked": candidates, "rationale": "fallback"}, tokens_prompt=10, tokens_completion=5, duration_seconds=0.1)

    monkeypatch.setattr(LLMProviderClient, "rerank_once", fake_once)
    orch = LLMOrchestrator()
    candidates = [{"sku": "s1", "name": "A", "price_cents": 1, "stock": 1}]
    out = orch.rerank_tiered("u1", candidates, {}, confidence=0.6)
    assert out and out[0]["sku"] == "s1"
    assert len(calls) >= 2
    assert calls[0][0] == "openai"
    assert calls[1][0] == "ollama"


def test_rerank_tiered_tenant_policy_override(monkeypatch):
    os.environ["LLM_PROVIDER_FALLBACK_STANDARD"] = "openai,ollama"
    os.environ["LLM_PROVIDER_TIER_STANDARD"] = "openai"
    os.environ["LLM_MODEL_TIER_STANDARD"] = "gpt-4o-mini"

    monkeypatch.setattr(TokenBudget, "__init__", lambda self, r: None)
    monkeypatch.setattr(TokenBudget, "check_budget", lambda self, uid, tier, estimated_tokens: (True, "ok", 10000))
    monkeypatch.setattr(TokenBudget, "record_usage", lambda self, uid, tokens, cost: None)

    calls = []

    def fake_once(self, candidates, constraints, uid=None, provider=None, model=None, allow_stub_fallback=False, trace_id=None, tier=None, tenant_id=None):
        calls.append((provider, tenant_id))
        return LLMResult(output={"ranked": candidates, "rationale": "ok"}, tokens_prompt=2, tokens_completion=1, duration_seconds=0.01)

    monkeypatch.setattr(LLMProviderClient, "rerank_once", fake_once)
    orch = LLMOrchestrator()

    def fake_get_override(config_key, tenant_id=None):
        if config_key != "llm_routing_policy":
            return None
        if tenant_id == "tenant-a":
            return {"fallback": {"standard": ["anthropic", "openai"]}}
        return {}

    monkeypatch.setattr(orch.tenant_config, "get_override", fake_get_override)
    candidates = [{"sku": "s1", "name": "A", "price_cents": 1, "stock": 1}]
    out = orch.rerank_tiered("u1", candidates, {}, confidence=0.6, tenant_id="tenant-a")
    assert out and out[0]["sku"] == "s1"
    assert calls
    assert calls[0][0] == "anthropic"
    assert calls[0][1] == "tenant-a"
