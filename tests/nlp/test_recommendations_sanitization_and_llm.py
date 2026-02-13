import os
import json
import asyncio

from src.app.services.recommendations import RecommendationService
from src.app.services.llm import LLMProviderClient, LLMOrchestrator
from src.app.config import get_settings


def test_log_decision_sanitizes_query_and_context(tmp_path):
    # Ensure SQLite fallback for tests
    os.environ["DATABASE_URL"] = f"sqlite+pysqlite:///{tmp_path}/test.sqlite"
    svc = RecommendationService()
    candidates = [
        {"id": "1", "sku": "SKU1", "name": "Laptop A", "price_cents": 900, "currency": "USD", "stock": 5, "specs": {"ram": "16GB"}},
        {"id": "2", "sku": "SKU2", "name": "Laptop B", "price_cents": 1100, "currency": "USD", "stock": 0, "specs": {"ram": "32GB"}},
    ]
    constraints = svc.parse_constraints("prefer under $1000 lenovo 16gb")
    proposal = {"decision_mode": "llm", "ranked_skus": ["SKU1", "SKU2"], "rationale": "test"}
    dec_id = svc.log_decision(uid="user-1", query="email me at bob@example.com", retrieved_context={"ip": "10.0.0.1"}, proposal=proposal, policy_version="v1")
    assert dec_id is not None
    # Read back decision to confirm redaction
    from src.app.models.db import db_session
    with db_session() as db:
        row = db.execute("SELECT input_data, retrieved_context FROM decision_logs WHERE id = :id", {"id": dec_id}).fetchone()
        assert row is not None
        input_data = json.loads(row[0])
        ctx = json.loads(row[1])
        s_in = json.dumps(input_data)
        s_ctx = json.dumps(ctx)
        assert "[REDACTED_EMAIL]" in s_in
        assert "[REDACTED_IP]" in s_ctx


def test_maybe_llm_rerank_uses_ollama_when_enabled(monkeypatch):
    # Configure env so LLMOrchestrator uses ollama
    os.environ["LLM_PROVIDER"] = "ollama"
    os.environ["LLM_MODEL"] = "llama3:8b"
    # Clear cached settings to pick up env changes
    try:
        get_settings.cache_clear()
    except Exception:
        pass

    # Monkeypatch the Ollama CLI call to return a valid JSON
    def fake_run(self, model, prompt, timeout=15):
        return '{"ranked_skus":["SKU2","SKU1"],"rationale":"demo"}'

    monkeypatch.setattr(LLMProviderClient, "_call_ollama_cli", fake_run)

    svc = RecommendationService()
    candidates = [
        {"id": "1", "sku": "SKU1", "name": "Laptop A", "price_cents": 900, "currency": "USD", "stock": 5, "specs": {}},
        {"id": "2", "sku": "SKU2", "name": "Laptop B", "price_cents": 1100, "currency": "USD", "stock": 0, "specs": {}},
    ]
    constraints = svc.parse_constraints("prefer lenovo under $1200")
    ranked = svc.maybe_llm_rerank(uid="demo", candidates=candidates, constraints=constraints, use_llm=True)
    # Expect order per fake JSON
    assert [c["sku"] for c in ranked] == ["SKU2", "SKU1"]
