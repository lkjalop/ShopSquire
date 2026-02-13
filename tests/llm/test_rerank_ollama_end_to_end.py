import os
import json
import pytest

from src.app.services.llm import LLMProviderClient


def test_llm_rerank_ollama_end_to_end_with_json(monkeypatch):
    # Force provider to ollama; model string can be any present locally
    os.environ["LLM_PROVIDER"] = "ollama"
    os.environ["LLM_MODEL"] = "llama3:8b"

    # Candidates with clear deterministic preference for stub fallback
    candidates = [
        {"sku": "aa", "name": "BrandX Laptop", "price_cents": 90000, "stock": 10},
        {"sku": "bb", "name": "BrandY Ultrabook", "price_cents": 120000, "stock": 0},
        {"sku": "cc", "name": "Generic Laptop", "price_cents": 80000, "stock": 5},
    ]
    constraints = {"budget_max": 100000, "brands": ["brandx"]}

    # Monkeypatch the ollama CLI call to return JSON we expect the parser to handle
    def fake_ollama_run(model, prompt, timeout=15):
        return json.dumps({"ranked_skus": ["aa", "cc", "bb"], "rationale": "test"})

    client = LLMProviderClient(provider="ollama", model=os.environ["LLM_MODEL"], api_key="")
    monkeypatch.setattr(client, "_call_ollama_cli", fake_ollama_run)

    res = client.rerank(candidates, constraints)
    ranked = res.output.get("ranked")
    assert isinstance(ranked, list) and len(ranked) == 3
    assert [c["sku"] for c in ranked] == ["aa", "cc", "bb"]


def test_llm_rerank_ollama_fallback(monkeypatch):
    # Force provider to ollama; model string can be any present locally
    os.environ["LLM_PROVIDER"] = "ollama"
    os.environ["LLM_MODEL"] = "llama3:8b"

    # Candidates crafted for deterministic fallback ordering
    candidates = [
        {"sku": "aa", "name": "BrandX Laptop", "price_cents": 90000, "stock": 10},
        {"sku": "bb", "name": "BrandY Ultrabook", "price_cents": 120000, "stock": 0},
        {"sku": "cc", "name": "Generic Laptop", "price_cents": 80000, "stock": 5},
    ]
    constraints = {"budget_max": 100000, "brands": ["brandx"]}

    # Monkeypatch ollama CLI to simulate absence/failure -> None, forcing fallback
    def fake_ollama_run(model, prompt, timeout=15):
        return None

    client = LLMProviderClient(provider="ollama", model=os.environ["LLM_MODEL"], api_key="")
    monkeypatch.setattr(client, "_call_ollama_cli", fake_ollama_run)

    res = client.rerank(candidates, constraints)
    ranked = res.output.get("ranked")
    assert isinstance(ranked, list) and len(ranked) == 3
    # Deterministic fallback should place 'aa' first given stock, budget, brand match
    assert ranked[0]["sku"] == "aa"
