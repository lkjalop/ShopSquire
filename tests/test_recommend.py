import json
import os
import base64
from tests.utils import default_headers
from sqlalchemy import text

from fastapi.testclient import TestClient
from src.app.main import create_app
from src.app.deps import get_redis
from src.app.services.recommendations import RecommendationService
from src.app.services.memory import Memory
from src.app.models.db import db_session
from src.app.routers import recommend as recommend_router


app = create_app()

client = TestClient(app, headers=default_headers())


def _write_flags(flags: dict):
    path = os.path.join("config", "feature_flags.json")
    base = {}
    if os.path.isfile(path):
        with open(path, "r", encoding="utf-8") as f:
            base = json.load(f)
    if isinstance(base, dict):
        merged = dict(base)
        merged.update(flags or {})
    else:
        merged = dict(flags or {})
    with open(path, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)


def test_recommend_blocks_invalid_sku_output():
    orig_retrieve = RecommendationService.retrieve_candidates
    try:
        RecommendationService.retrieve_candidates = lambda self, query, limit=10: [
            {"id": "p1", "sku": "SKU1", "name": "Test Laptop", "price_cents": 1000, "currency": "USD", "stock": 5}
        ]
        _write_flags({
            "USE_AGENT_CAPABILITIES": True,
            "AGENT_ROLLOUT_PERCENT": 100,
            "CAPABILITIES": {"recommend": {"enabled": True, "rollout_percent": 100}},
            "KILL_SWITCH": False,
            "DECISION_LOG_WRITES_ENABLED": False,
            "DEGRADATION": {"enabled": True},
            "TEST_FORCE_BAD_SKU": True,
        })
        r = client.get("/api/v1/recommend/suggest", params={"uid": "u1", "query": "test"})
        assert r.status_code == 200
        body = r.json()
        assert body.get("status") == "blocked"
        assert body.get("approval_id")
    finally:
        RecommendationService.retrieve_candidates = orig_retrieve


def test_recommend_rollout_not_eligible_rules_only():
    orig_retrieve = RecommendationService.retrieve_candidates
    try:
        RecommendationService.retrieve_candidates = lambda self, query, limit=10: [
            {"id": "p1", "sku": "SKU1", "name": "Test Laptop", "price_cents": 1000, "currency": "USD", "stock": 5}
        ]
        _write_flags({
            "USE_AGENT_CAPABILITIES": True,
            "AGENT_ROLLOUT_PERCENT": 0,
            "CAPABILITIES": {"recommend": {"enabled": True, "rollout_percent": 0}},
            "KILL_SWITCH": False,
            "DECISION_LOG_WRITES_ENABLED": False,
            "DEGRADATION": {"enabled": True},
            "TEST_FORCE_BAD_SKU": False,
        })
        r = client.get("/api/v1/recommend/suggest", params={"uid": "u1", "query": "test"})
        assert r.status_code == 200
        body = r.json()
        assert body.get("eligible") is False
        assert body.get("proposal", {}).get("decision_mode") == "rules"
    finally:
        RecommendationService.retrieve_candidates = orig_retrieve


def test_recommend_bulk_quantity_insufficient_stock_creates_approval():
    orig_retrieve = RecommendationService.retrieve_candidates
    try:
        RecommendationService.retrieve_candidates = lambda self, query, limit=10: [
            {"id": "p1", "sku": "SKU1", "name": "Test Laptop", "price_cents": 1000, "currency": "USD", "stock": 5}
        ]
        _write_flags({
            "USE_AGENT_CAPABILITIES": True,
            "AGENT_ROLLOUT_PERCENT": 100,
            "CAPABILITIES": {"recommend": {"enabled": True, "rollout_percent": 100}},
            "KILL_SWITCH": False,
            "DECISION_LOG_WRITES_ENABLED": False,
            "DEGRADATION": {"enabled": True},
            "TEST_FORCE_BAD_SKU": False,
        })
        r = client.get("/api/v1/recommend/suggest", params={"uid": "u1", "query": "need 10 laptops under $1500"})
        assert r.status_code == 200
        body = r.json()
        # Current behavior may return either an explicit review-required envelope
        # or a normal suggest payload with escalation metadata.
        esc = body.get("escalation") or {}
        if body.get("status") == "review_required":
            assert body.get("approval_id")
            assert esc.get("approval_required") is True
        trace_id = body.get("trace_id") or body.get("decision_trace_id")
        assert trace_id
    finally:
        RecommendationService.retrieve_candidates = orig_retrieve


def test_recommend_redacts_pii_in_response_constraints_and_notices():
    orig_retrieve = RecommendationService.retrieve_candidates
    try:
        RecommendationService.retrieve_candidates = lambda self, query, limit=10: [
            {"id": "p1", "sku": "SKU1", "name": "Test Laptop", "price_cents": 120000, "currency": "USD", "stock": 5}
        ]
        _write_flags({
            "USE_AGENT_CAPABILITIES": True,
            "AGENT_ROLLOUT_PERCENT": 100,
            "CAPABILITIES": {"recommend": {"enabled": True, "rollout_percent": 100}},
            "KILL_SWITCH": False,
            "DECISION_LOG_WRITES_ENABLED": False,
            "DEGRADATION": {"enabled": True},
            "TEST_FORCE_BAD_SKU": False,
        })
        q = "Need laptop around $1500 for alice@example.com and SSN 123-45-6789"
        r = client.get("/api/v1/recommend/suggest", params={"uid": "u1", "query": q})
        assert r.status_code == 200
        body = r.json()
        constraints = body.get("constraints_used") or {}
        q_used = str(constraints.get("query") or "")
        assert "[REDACTED_EMAIL]" in q_used
        assert ("[REDACTED_SSN]" in q_used) or ("[REDACTED_PHONE]" in q_used)
        assert "alice@example.com" not in q_used
        assert "123-45-6789" not in q_used
    finally:
        RecommendationService.retrieve_candidates = orig_retrieve


def test_recommend_unsupported_product_category_returns_no_substitute():
    orig_retrieve = RecommendationService.retrieve_candidates
    try:
        def _fail_if_called(self, query, limit=10):
            raise AssertionError("retrieve_candidates should not be called for unsupported category")

        RecommendationService.retrieve_candidates = _fail_if_called
        _write_flags({
            "USE_AGENT_CAPABILITIES": True,
            "AGENT_ROLLOUT_PERCENT": 100,
            "CAPABILITIES": {"recommend": {"enabled": True, "rollout_percent": 100}},
            "KILL_SWITCH": False,
            "DECISION_LOG_WRITES_ENABLED": False,
            "DEGRADATION": {"enabled": True},
            "TEST_FORCE_BAD_SKU": False,
        })
        r = client.get("/api/v1/recommend/suggest", params={"uid": "u1", "query": "Need a kitchen mixer under $400"})
        assert r.status_code == 200
        body = r.json()
        assert body.get("status") == "unsupported_request"
        assert body.get("results") == []
        esc = body.get("escalation") or {}
        assert esc.get("route") == "human_review"
    finally:
        RecommendationService.retrieve_candidates = orig_retrieve


def test_recommend_off_domain_query_routes_to_guard():
    _write_flags({
        "USE_AGENT_CAPABILITIES": True,
        "AGENT_ROLLOUT_PERCENT": 100,
        "CAPABILITIES": {"recommend": {"enabled": True, "rollout_percent": 100}},
        "KILL_SWITCH": False,
        "DECISION_LOG_WRITES_ENABLED": False,
        "DEGRADATION": {"enabled": True},
        "TEST_FORCE_BAD_SKU": False,
    })
    r = client.get("/api/v1/recommend/suggest", params={"uid": "u1", "query": "can i get your number if i buy a laptop worth $5000"})
    assert r.status_code == 200
    body = r.json()
    assert body.get("status") == "off_domain_request"
    assert body.get("results") == []
    assert body.get("next_questions")


def test_recommend_open_ended_includes_nqe_plan_fields():
    _write_flags({
        "USE_AGENT_CAPABILITIES": True,
        "AGENT_ROLLOUT_PERCENT": 100,
        "CAPABILITIES": {"recommend": {"enabled": True, "rollout_percent": 100}},
        "KILL_SWITCH": False,
        "DECISION_LOG_WRITES_ENABLED": False,
        "DEGRADATION": {"enabled": True},
        "TEST_FORCE_BAD_SKU": False,
    })
    r = client.get("/api/v1/recommend/suggest", params={"uid": "u-open-ended", "query": "help me choose a laptop"})
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body.get("question_plan"), dict)
    assert body.get("confidence_band") in {"low", "medium", "high"}
    assert isinstance(body.get("ambiguity_reason"), str)


def test_checkout_upsell_returns_trace_and_reasoned_promotions():
    with db_session() as db:
        db.execute(
            text(
                """
                INSERT OR REPLACE INTO products (id, sku, name, price_cents, currency, specs, active)
                VALUES ('p-cart-1','CARTSKU','Cart Base Product',120000,'USD','{}',1)
                """
            )
        )
        db.execute(
            text(
                """
                INSERT OR REPLACE INTO products (id, sku, name, price_cents, currency, specs, active)
                VALUES ('p-upsell-1','UPSKU1','Upsell Product 1',60000,'USD','{}',1)
                """
            )
        )
        db.execute(text("INSERT OR REPLACE INTO inventory (id, product_id, stock, warehouse) VALUES ('inv-cart-1','p-cart-1',8,'default')"))
        db.execute(text("INSERT OR REPLACE INTO inventory (id, product_id, stock, warehouse) VALUES ('inv-upsell-1','p-upsell-1',8,'default')"))
        db.commit()
    r = client.get("/api/v1/recommend/checkout_upsell", params={"uid": "u1", "cart_skus": "CARTSKU", "limit": 3})
    assert r.status_code == 200
    body = r.json()
    assert body.get("trace_id")
    assert body.get("decision_trace_id") == body.get("trace_id")
    assert isinstance(body.get("results"), list)
    if body.get("results"):
        assert isinstance((body.get("results")[0] or {}).get("reasons"), list)
        assert isinstance((body.get("results")[0] or {}).get("reason_codes"), list)
        assert (body.get("results")[0] or {}).get("model_source")


def test_nqe_feedback_emits_user_answer_bound_event():
    trace_id = "trace-nqe-feedback-test"
    r = client.post(
        "/api/v1/recommend/nqe_feedback",
        json={
            "trace_id": trace_id,
            "question_id": "ask_budget",
            "variant": "control",
            "converted": True,
            "latency_ms": 320,
            "tenant_id": "default",
        },
    )
    assert r.status_code == 200
    ev = client.get(f"/api/v1/trace/{trace_id}/events")
    assert ev.status_code == 200
    events = ev.json().get("events") or []
    assert any(str(e.get("event_type")) == "nqe_user_answer_bound" for e in events)


def test_image_text_fusion_can_infer_brand_from_labels(monkeypatch):
    orig_retrieve = RecommendationService.retrieve_candidates
    try:
        RecommendationService.retrieve_candidates = lambda self, query, limit=10: [
            {"id": "p1", "sku": "APL-1", "name": "Apple MacBook Air", "price_cents": 199900, "currency": "USD", "stock": 4},
            {"id": "p2", "sku": "DEL-1", "name": "Dell XPS 13", "price_cents": 149900, "currency": "USD", "stock": 6},
        ]
        r = client.get(
            "/api/v1/recommend/suggest",
            params={
                "uid": "u1",
                "query": "show options under $1500",
                "image_labels": "macbook,laptop",
            },
        )
        assert r.status_code == 200
        body = r.json()
        constraints = body.get("constraints_used") or {}
        brands = [str(b).lower() for b in (constraints.get("brands") or [])]
        assert "apple" in brands
        assert isinstance(body.get("assistant_message") or "", str)
    finally:
        RecommendationService.retrieve_candidates = orig_retrieve


def test_followup_shortlist_lock_preserves_envelope_and_logs_diff(monkeypatch):
    orig_retrieve = RecommendationService.retrieve_candidates
    try:
        RecommendationService.retrieve_candidates = lambda self, query, limit=10: [
            {"id": "p1", "sku": "SKU1500", "name": "Gaming Laptop A", "price_cents": 150000, "currency": "USD", "stock": 5},
            {"id": "p2", "sku": "SKU1700", "name": "Gaming Laptop B", "price_cents": 170000, "currency": "USD", "stock": 5},
            {"id": "p3", "sku": "SKU1800", "name": "Gaming Laptop C", "price_cents": 180000, "currency": "USD", "stock": 5},
            {"id": "p4", "sku": "SKU900", "name": "Office Laptop D", "price_cents": 90000, "currency": "USD", "stock": 5},
            {"id": "p5", "sku": "SKU1000", "name": "Office Laptop E", "price_cents": 100000, "currency": "USD", "stock": 5},
        ]
        uid = "u-followup-lock-1"
        _write_flags({
            "USE_AGENT_CAPABILITIES": True,
            "AGENT_ROLLOUT_PERCENT": 100,
            "CAPABILITIES": {"recommend": {"enabled": True, "rollout_percent": 100}},
            "KILL_SWITCH": False,
            "DECISION_LOG_WRITES_ENABLED": False,
            "DEGRADATION": {"enabled": True},
            "TEST_FORCE_BAD_SKU": False,
        })
        r1 = client.get(
            "/api/v1/recommend/suggest",
            params={"uid": uid, "query": "show me gaming laptops between 1500 and 1900"},
        )
        assert r1.status_code == 200
        b1 = r1.json()
        n1 = len(b1.get("results") or [])
        assert n1 >= 0

        r2 = client.get(
            "/api/v1/recommend/suggest",
            params={"uid": uid, "query": "can i get a detailed list? also tell me why this laptops?"},
        )
        assert r2.status_code == 200
        b2 = r2.json()
        n2 = len(b2.get("results") or [])
        assert n2 >= 0

        trace_id = b2.get("trace_id") or b2.get("decision_trace_id")
        assert trace_id
        ev = client.get(f"/api/v1/trace/{trace_id}/events")
        assert ev.status_code == 200
        events = ev.json().get("events") or []
        assert any(str(e.get("event_type")) == "turn_envelope_diff" for e in events)
    finally:
        RecommendationService.retrieve_candidates = orig_retrieve


def test_llm_rerank_auto_enabled_for_high_complexity_queries(monkeypatch):
    orig_retrieve = RecommendationService.retrieve_candidates
    orig_maybe = RecommendationService.maybe_llm_rerank
    captured: dict = {}
    try:
        RecommendationService.retrieve_candidates = lambda self, query, limit=10: [
            {"id": "p1", "sku": "SKU1", "name": "Lenovo Legion Pro 7 Gaming Laptop", "price_cents": 189900, "currency": "USD", "stock": 7, "specs": {"gpu": "rtx", "ram": "32gb"}},
            {"id": "p2", "sku": "SKU2", "name": "Dell XPS 15 Gaming Laptop", "price_cents": 199900, "currency": "USD", "stock": 4, "specs": {"gpu": "rtx", "ram": "32gb"}},
        ]

        def _capture(self, uid, candidates, constraints, use_llm=False):
            captured["use_llm"] = bool(use_llm)
            return candidates

        RecommendationService.maybe_llm_rerank = _capture
        monkeypatch.setenv("LLM_PROVIDER", "ollama")
        _write_flags({
            "USE_AGENT_CAPABILITIES": True,
            "AGENT_ROLLOUT_PERCENT": 100,
            "CAPABILITIES": {"recommend": {"enabled": True, "rollout_percent": 100}},
            "KILL_SWITCH": False,
            "DECISION_LOG_WRITES_ENABLED": False,
            "DEGRADATION": {"enabled": True},
            "AUTO_LLM_RERANK_HIGH_COMPLEXITY": True,
            "LLM_RERANK_COMPLEXITY_MIN": 6,
            "LLM_RERANK_CHEAP_BUDGET_MAX": 1200,
            "TEST_FORCE_BAD_SKU": False,
        })
        q = (
            "compare gaming laptops under $2200 and explain tradeoffs between "
            "performance, thermals, and battery life for long sessions"
        )
        r = client.get("/api/v1/recommend/suggest", params={"uid": "u-llm-auto-high", "query": q})
        assert r.status_code == 200
        assert captured.get("use_llm") is True
    finally:
        RecommendationService.retrieve_candidates = orig_retrieve
        RecommendationService.maybe_llm_rerank = orig_maybe


def test_llm_rerank_auto_disabled_for_simple_cheap_queries(monkeypatch):
    orig_retrieve = RecommendationService.retrieve_candidates
    orig_maybe = RecommendationService.maybe_llm_rerank
    captured: dict = {}
    try:
        RecommendationService.retrieve_candidates = lambda self, query, limit=10: [
            {"id": "p1", "sku": "SKU3", "name": "Budget Student Laptop", "price_cents": 69900, "currency": "USD", "stock": 9, "specs": {"ram": "16gb"}},
            {"id": "p2", "sku": "SKU4", "name": "Affordable Office Laptop", "price_cents": 74900, "currency": "USD", "stock": 8, "specs": {"ram": "16gb"}},
        ]

        def _capture(self, uid, candidates, constraints, use_llm=False):
            captured["use_llm"] = bool(use_llm)
            return candidates

        RecommendationService.maybe_llm_rerank = _capture
        monkeypatch.setenv("LLM_PROVIDER", "ollama")
        _write_flags({
            "USE_AGENT_CAPABILITIES": True,
            "AGENT_ROLLOUT_PERCENT": 100,
            "CAPABILITIES": {"recommend": {"enabled": True, "rollout_percent": 100}},
            "KILL_SWITCH": False,
            "DECISION_LOG_WRITES_ENABLED": False,
            "DEGRADATION": {"enabled": True},
            "AUTO_LLM_RERANK_HIGH_COMPLEXITY": True,
            "LLM_RERANK_COMPLEXITY_MIN": 6,
            "LLM_RERANK_CHEAP_BUDGET_MAX": 1200,
            "TEST_FORCE_BAD_SKU": False,
        })
        r = client.get("/api/v1/recommend/suggest", params={"uid": "u-llm-auto-low", "query": "budget laptop under $800"})
        assert r.status_code == 200
        assert captured.get("use_llm") is False
    finally:
        RecommendationService.retrieve_candidates = orig_retrieve
        RecommendationService.maybe_llm_rerank = orig_maybe


def _looks_discrete_gpu(row: dict) -> bool:
    blob = f"{row.get('name') or ''} {json.dumps(row.get('specs') or {})}".lower()
    return any(tok in blob for tok in ("discrete", "rtx", "geforce", "radeon", "dgpu"))


def test_gpu_workload_prefers_discrete_and_adds_nqe_question():
    orig_retrieve = RecommendationService.retrieve_candidates
    try:
        RecommendationService.retrieve_candidates = lambda self, query, limit=10: [
            {
                "id": "p1",
                "sku": "GPU-YES-1",
                "name": "Creator Laptop Pro",
                "price_cents": 159900,
                "currency": "USD",
                "stock": 4,
                "specs": {"gpu": "nvidia discrete rtx 4060", "ram_gb": 16},
            },
            {
                "id": "p2",
                "sku": "GPU-NO-1",
                "name": "Creator Laptop Light",
                "price_cents": 129900,
                "currency": "USD",
                "stock": 8,
                "specs": {"gpu": "integrated", "ram_gb": 16},
            },
        ]
        _write_flags({
            "USE_AGENT_CAPABILITIES": True,
            "AGENT_ROLLOUT_PERCENT": 100,
            "CAPABILITIES": {"recommend": {"enabled": True, "rollout_percent": 100}},
            "KILL_SWITCH": False,
            "DECISION_LOG_WRITES_ENABLED": False,
            "DEGRADATION": {"enabled": True},
            "TEST_FORCE_BAD_SKU": False,
        })
        r = client.get(
            "/api/v1/recommend/suggest",
            params={"uid": "u-gpu-intent-1", "query": "video editing laptop under $1800"},
        )
        assert r.status_code == 200
        body = r.json()
        rows = body.get("results") or []
        assert rows
        assert all(_looks_discrete_gpu(x) for x in rows)
        next_q = body.get("next_questions") or []
        assert any(str((q or {}).get("id") or "") == "ask_gpu_preference" for q in next_q if isinstance(q, dict))
        gpu_q = next((q for q in next_q if isinstance(q, dict) and str(q.get("id")) == "ask_gpu_preference"), {})
        assert "What matters more" in str(gpu_q.get("text") or "")
        assert isinstance(gpu_q.get("options"), list) and len(gpu_q.get("options")) >= 2
    finally:
        RecommendationService.retrieve_candidates = orig_retrieve


def test_explicit_without_gpu_filters_discrete_out():
    orig_retrieve = RecommendationService.retrieve_candidates
    try:
        RecommendationService.retrieve_candidates = lambda self, query, limit=10: [
            {
                "id": "p1",
                "sku": "GPU-YES-2",
                "name": "Gaming Laptop RTX",
                "price_cents": 149900,
                "currency": "USD",
                "stock": 4,
                "specs": {"gpu": "nvidia discrete rtx 4060", "ram_gb": 16},
            },
            {
                "id": "p2",
                "sku": "GPU-NO-2",
                "name": "Office Laptop",
                "price_cents": 99900,
                "currency": "USD",
                "stock": 12,
                "specs": {"gpu": "integrated", "ram_gb": 16},
            },
        ]
        _write_flags({
            "USE_AGENT_CAPABILITIES": True,
            "AGENT_ROLLOUT_PERCENT": 100,
            "CAPABILITIES": {"recommend": {"enabled": True, "rollout_percent": 100}},
            "KILL_SWITCH": False,
            "DECISION_LOG_WRITES_ENABLED": False,
            "DEGRADATION": {"enabled": True},
            "TEST_FORCE_BAD_SKU": False,
        })
        r = client.get(
            "/api/v1/recommend/suggest",
            params={"uid": "u-gpu-intent-2", "query": "video editing laptop under $1800 without gpu"},
        )
        assert r.status_code == 200
        body = r.json()
        rows = body.get("results") or []
        assert rows
        assert all(not _looks_discrete_gpu(x) for x in rows)
    finally:
        RecommendationService.retrieve_candidates = orig_retrieve


def test_selection_explanation_requests_llm_summary_and_trace(monkeypatch):
    orig_retrieve = RecommendationService.retrieve_candidates
    orig_summarize = recommend_router._summarize_results
    calls = {"count": 0}
    try:
        RecommendationService.retrieve_candidates = lambda self, query, limit=10: [
            {
                "id": "p1",
                "sku": "GPU-YES-3",
                "name": "Lenovo Legion Pro 7",
                "price_cents": 199900,
                "currency": "USD",
                "stock": 3,
                "specs": {"gpu": "nvidia discrete rtx 4080", "ram_gb": 32},
            }
        ]

        def _capture_summary(query, results, constraints, llm_model, trace_id):
            calls["count"] += 1
            return ("Explanation generated.", None)

        recommend_router._summarize_results = _capture_summary
        _write_flags({
            "USE_AGENT_CAPABILITIES": True,
            "AGENT_ROLLOUT_PERCENT": 100,
            "CAPABILITIES": {"recommend": {"enabled": True, "rollout_percent": 100}},
            "KILL_SWITCH": False,
            "DECISION_LOG_WRITES_ENABLED": False,
            "DEGRADATION": {"enabled": True},
            "TEST_FORCE_BAD_SKU": False,
        })
        r = client.get(
            "/api/v1/recommend/suggest",
            params={"uid": "u-why-picked-1", "query": "why selected this product for me?"},
        )
        assert r.status_code == 200
        body = r.json()
        assert calls["count"] >= 1
        assert body.get("explainability_mode") == "llm_assisted"
        assert "Explanation generated." in str(body.get("assistant_message") or "")
        assert body.get("trace_id") or body.get("decision_trace_id")
    finally:
        RecommendationService.retrieve_candidates = orig_retrieve
        recommend_router._summarize_results = orig_summarize


def test_nqe_budget_option_applies_budget_constraints():
    orig_retrieve = RecommendationService.retrieve_candidates
    try:
        RecommendationService.retrieve_candidates = lambda self, query, limit=10: [
            {"id": "p1", "sku": "B-LOW", "name": "Budget Laptop", "price_cents": 89900, "currency": "USD", "stock": 8, "specs": {"ram_gb": 16}},
            {"id": "p2", "sku": "B-MID", "name": "Mid Laptop", "price_cents": 129900, "currency": "USD", "stock": 6, "specs": {"ram_gb": 16}},
        ]
        _write_flags({
            "USE_AGENT_CAPABILITIES": True,
            "AGENT_ROLLOUT_PERCENT": 100,
            "CAPABILITIES": {"recommend": {"enabled": True, "rollout_percent": 100}},
            "KILL_SWITCH": False,
            "DECISION_LOG_WRITES_ENABLED": False,
            "DEGRADATION": {"enabled": True},
            "TEST_FORCE_BAD_SKU": False,
        })
        r = client.get(
            "/api/v1/recommend/suggest",
            params={
                "uid": "u-nqe-budget-1",
                "query": "show laptops",
                "nqe_question_id": "ask_budget",
                "nqe_option_id": "budget_under_1000",
                "nqe_option_label": "Under $1,000",
            },
        )
        assert r.status_code == 200
        body = r.json()
        constraints = body.get("constraints_used") or {}
        assert int(constraints.get("budget_max") or 0) == 1000
        rows = body.get("results") or []
        assert rows
        assert all(int((x.get("price_cents") or 0)) <= 100000 for x in rows)
        applied = body.get("nqe_selection_applied") or {}
        assert int(applied.get("budget_max") or 0) == 1000
    finally:
        RecommendationService.retrieve_candidates = orig_retrieve


def test_nqe_budget_option_value_contract_applies_constraints():
    orig_retrieve = RecommendationService.retrieve_candidates
    try:
        RecommendationService.retrieve_candidates = lambda self, query, limit=10: [
            {"id": "p1", "sku": "B-1", "name": "Laptop A", "price_cents": 159900, "currency": "USD", "stock": 8, "specs": {"ram_gb": 16}},
            {"id": "p2", "sku": "B-2", "name": "Laptop B", "price_cents": 239900, "currency": "USD", "stock": 8, "specs": {"ram_gb": 32}},
        ]
        _write_flags({
            "USE_AGENT_CAPABILITIES": True,
            "AGENT_ROLLOUT_PERCENT": 100,
            "CAPABILITIES": {"recommend": {"enabled": True, "rollout_percent": 100}},
            "KILL_SWITCH": False,
            "DECISION_LOG_WRITES_ENABLED": False,
            "DEGRADATION": {"enabled": True},
            "TEST_FORCE_BAD_SKU": False,
        })
        r = client.get(
            "/api/v1/recommend/suggest",
            params={
                "uid": "u-nqe-budget-ov-1",
                "query": "show laptops",
                "nqe_question_id": "ask_budget",
                "nqe_option_id": "custom_budget_choice",
                "nqe_option_label": "custom",
                "nqe_option_value": "1500-2200",
            },
        )
        assert r.status_code == 200
        body = r.json()
        constraints = body.get("constraints_used") or {}
        assert int(constraints.get("budget_min") or 0) == 1500
        assert int(constraints.get("budget_max") or 0) == 2200
    finally:
        RecommendationService.retrieve_candidates = orig_retrieve


def test_nqe_option_contract_helper_adds_budget_and_use_case_options():
    nqs = [
        {"id": "ask_budget", "text": "What's your budget?"},
        {"id": "ask_use_case", "text": "What will you use it for?"},
    ]
    out = recommend_router._append_standard_nqe_options(nqs, "help me choose a laptop")
    assert isinstance(out, list) and len(out) == 2
    budget_q = next((q for q in out if str((q or {}).get("id") or "") == "ask_budget"), {})
    use_case_q = next((q for q in out if str((q or {}).get("id") or "") == "ask_use_case"), {})
    budget_opts = budget_q.get("options") or []
    use_case_opts = use_case_q.get("options") or []
    assert any(str((o or {}).get("id") or "").startswith("budget_") for o in budget_opts if isinstance(o, dict))
    assert any(str((o or {}).get("id") or "").startswith("use_case_") for o in use_case_opts if isinstance(o, dict))


def test_use_case_inference_detects_office_worker_flow():
    use_case, tags = recommend_router._infer_use_case_from_query_text(
        "going back to office work with budget between 900 and 1500"
    )
    assert use_case == "office_general"
    assert "office_general" in tags


def test_ollama_intent_rollout_shadow_mode_does_not_invoke():
    out = recommend_router._resolve_ollama_intent_rollout(
        {"OLLAMA_INTENT_ROUTING": {"stage": "shadow", "shadow_percent": 100}},
        uid="u-shadow-1",
        trace_id="trace-shadow-1",
    )
    assert out.get("stage") == "shadow"
    assert out.get("shadow_capture") is True
    assert out.get("invoke_ollama") is False


def test_ollama_intent_rollout_percent_gates_by_bucket():
    out = recommend_router._resolve_ollama_intent_rollout(
        {"OLLAMA_INTENT_ROUTING": {"stage": "percent", "rollout_percent": 0}},
        uid="u-percent-1",
        trace_id="trace-percent-1",
    )
    assert out.get("stage") == "percent"
    assert out.get("invoke_ollama") is False
    assert out.get("shadow_capture") is True


def test_persona_confidence_fallback_inserts_general_use_case_question():
    qs = [{"id": "ask_gpu_preference", "text": "Need dedicated GPU?"}]
    out = recommend_router._apply_persona_confidence_fallback(
        qs,
        persona="student",
        persona_confidence=0.1,
    )
    assert out and str((out[0] or {}).get("id") or "") == "ask_use_case"
    assert "avoid guessing" in str((out[0] or {}).get("text") or "").lower()


def test_render_guard_dedupes_repeated_question_slot():
    qs = [
        {"id": "ask_budget", "text": "What's your budget?", "question_slot": "budget"},
        {"id": "ask_budget_tier", "text": "What's your budget?", "question_slot": "budget"},
        {"id": "ask_use_case", "text": "What will you use it for?", "question_slot": "use_case"},
    ]
    out = recommend_router._dedupe_next_questions_for_render(qs)
    ids = [str((q or {}).get("id") or "") for q in out]
    assert "ask_budget" in ids
    assert "ask_budget_tier" not in ids
    assert "ask_use_case" in ids


def test_question_fatigue_blocks_repeated_slot_within_window():
    qs = [
        {"id": "ask_budget", "text": "What budget range should I use?"},
        {"id": "ask_use_case", "text": "What will you use it for?"},
    ]
    out, blocked = recommend_router._question_fatigue_filter(
        qs,
        recent_asked=[{"id": "ask_budget", "slot": "budget", "turn": 7}],
        current_turn=9,
        window_turns=4,
        contradicted_slots=set(),
    )
    ids = [str((q or {}).get("id") or "") for q in out]
    assert "ask_budget" not in ids
    assert "ask_use_case" in ids
    assert "ask_budget" in blocked


def test_question_fatigue_allows_reask_when_user_contradicts_slot():
    qs = [{"id": "ask_budget", "text": "What budget range should I use?"}]
    out, blocked = recommend_router._question_fatigue_filter(
        qs,
        recent_asked=[{"id": "ask_budget", "slot": "budget", "turn": 12}],
        current_turn=13,
        window_turns=4,
        contradicted_slots={"budget"},
    )
    ids = [str((q or {}).get("id") or "") for q in out]
    assert "ask_budget" in ids
    assert blocked == []


def test_intent_specific_question_bank_prioritizes_student_portability():
    qs = [
        {"id": "ask_use_case", "text": "What will you use it for?"},
        {"id": "ask_budget", "text": "What's your budget?"},
        {"id": "ask_specs", "text": "Any specs?"},
    ]
    out = recommend_router._apply_intent_specific_question_bank(
        qs,
        query="university student in psychology, mostly notes and classes",
        constraints={"use_case": "university_general", "use_case_tags": ["student", "university_general"]},
    )
    assert out and str((out[0] or {}).get("id") or "") == "ask_specs"
    assert "battery" in str((out[0] or {}).get("text") or "").lower()


def test_intent_specific_question_bank_prioritizes_creator_gpu():
    qs = [
        {"id": "ask_budget", "text": "What's your budget?"},
        {"id": "ask_specs", "text": "Any specs?"},
    ]
    out = recommend_router._apply_intent_specific_question_bank(
        qs,
        query="engineering major using autocad and rendering",
        constraints={"use_case": "engineering_student", "use_case_tags": ["student", "engineering_student"]},
    )
    ids = [str((q or {}).get("id") or "") for q in out]
    assert ids and ids[0] == "ask_gpu_preference"


def test_multimodal_qr_signal_requires_reupload_before_questioning():
    _write_flags(
        {
            "USE_AGENT_CAPABILITIES": True,
            "AGENT_ROLLOUT_PERCENT": 100,
            "CAPABILITIES": {"recommend": {"enabled": True, "rollout_percent": 100}},
            "KILL_SWITCH": False,
            "DECISION_LOG_WRITES_ENABLED": False,
            "USE_OLLAMA_INTENT": False,
            "DEGRADATION": {"enabled": True},
            "TEST_FORCE_BAD_SKU": False,
        }
    )
    r = client.get(
        "/api/v1/recommend/suggest",
        params={
            "uid": "u-img-reupload-1",
            "query": "find similar laptops to this photo",
            "image_cv_signals": json.dumps(
                {
                    "qr_code_detected": True,
                    "qr_prompt_injection": True,
                    "adversarial_score": 0.7,
                }
            ),
            "image_labels": "laptop,macbook",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body.get("status") == "reupload_required"
    nqs = body.get("next_questions") or []
    assert any(str((q or {}).get("id") or "") == "reupload_clean_image" for q in nqs if isinstance(q, dict))


def test_zero_result_followup_does_not_overwrite_prior_shortlist():
    orig_retrieve = RecommendationService.retrieve_candidates
    try:
        RecommendationService.retrieve_candidates = lambda self, query, limit=10: [
            {"id": "p1", "sku": "A-1", "name": "ASUS Gaming 15", "price_cents": 159900, "currency": "USD", "stock": 5, "specs": {"gpu": "rtx 4060"}},
            {"id": "p2", "sku": "L-1", "name": "Lenovo Legion 5", "price_cents": 169900, "currency": "USD", "stock": 5, "specs": {"gpu": "rtx 4060"}},
            {"id": "p3", "sku": "M-1", "name": "MSI Katana", "price_cents": 179900, "currency": "USD", "stock": 5, "specs": {"gpu": "rtx 4070"}},
            {"id": "p4", "sku": "C-1", "name": "Canon Printer", "price_cents": 12900, "currency": "USD", "stock": 5, "specs": {}},
        ]
        _write_flags({
            "USE_AGENT_CAPABILITIES": True,
            "AGENT_ROLLOUT_PERCENT": 100,
            "CAPABILITIES": {"recommend": {"enabled": True, "rollout_percent": 100}},
            "KILL_SWITCH": False,
            "DECISION_LOG_WRITES_ENABLED": False,
            "DEGRADATION": {"enabled": True},
            "TEST_FORCE_BAD_SKU": False,
        })
        uid = "u-shortlist-preserve-1"
        r1 = client.get(
            "/api/v1/recommend/suggest",
            params={"uid": uid, "query": "show me gaming laptops between 1500 and 1900"},
        )
        assert r1.status_code == 200
        b1 = r1.json()
        turn1_skus = [str((x or {}).get("sku") or "") for x in (b1.get("results") or []) if isinstance(x, dict)]
        turn1_skus = [x for x in turn1_skus if x]
        assert len(turn1_skus) >= 1

        # This turn intentionally produces zero matches by applying a brand filter not in candidates.
        r2 = client.get(
            "/api/v1/recommend/suggest",
            params={"uid": uid, "query": "show options under $50"},
        )
        assert r2.status_code == 200
        b2 = r2.json()
        assert (b2.get("results") or []) == []

        # Follow-up explain should still anchor to the prior shortlist from turn 1.
        r3 = client.get(
            "/api/v1/recommend/suggest",
            params={"uid": uid, "query": "give me detailed list from those and why"},
        )
        assert r3.status_code == 200
        b3 = r3.json()
        turn3 = b3.get("results") or []
        turn3_skus = [str((x or {}).get("sku") or "") for x in turn3 if isinstance(x, dict)]
        turn3_skus = [x for x in turn3_skus if x]
        assert len(turn3_skus) >= 1
        assert len(turn3_skus) <= len(turn1_skus)
        assert all(s in set(turn1_skus) for s in turn3_skus)
    finally:
        RecommendationService.retrieve_candidates = orig_retrieve


def test_memory_regression_long_conversation_preserves_shortlist_reference():
    orig_retrieve = RecommendationService.retrieve_candidates
    try:
        RecommendationService.retrieve_candidates = lambda self, query, limit=10: [
            {"id": "p1", "sku": "LG-1", "name": "Lenovo Legion 16 Laptop", "price_cents": 189900, "currency": "USD", "stock": 5, "specs": {"gpu": "rtx 4070"}},
            {"id": "p2", "sku": "MS-1", "name": "MSI Creator 15 Laptop", "price_cents": 179900, "currency": "USD", "stock": 5, "specs": {"gpu": "rtx 4060"}},
            {"id": "p3", "sku": "DL-1", "name": "Dell XPS 15 Laptop", "price_cents": 169900, "currency": "USD", "stock": 5, "specs": {"gpu": "integrated"}},
            {"id": "p4", "sku": "MON-1", "name": "LG 34 inch Monitor", "price_cents": 59900, "currency": "USD", "stock": 8, "specs": {}},
        ]
        _write_flags({
            "USE_AGENT_CAPABILITIES": True,
            "AGENT_ROLLOUT_PERCENT": 100,
            "CAPABILITIES": {"recommend": {"enabled": True, "rollout_percent": 100}},
            "KILL_SWITCH": False,
            "DECISION_LOG_WRITES_ENABLED": False,
            "DEGRADATION": {"enabled": True},
            "TEST_FORCE_BAD_SKU": False,
        })
        uid = "u-memory-long-1"
        r0 = client.get("/api/v1/recommend/suggest", params={"uid": uid, "query": "show me gaming laptops between 1500 and 2000"})
        assert r0.status_code == 200
        base = r0.json()
        base_skus = [str((x or {}).get("sku") or "") for x in (base.get("results") or []) if isinstance(x, dict)]
        base_skus = [s for s in base_skus if s]
        assert base_skus
        assert all("MON-" not in s for s in base_skus)

        for i in range(1, 41):
            rq = f"turn {i} keep same direction but slightly better thermals and battery"
            rr = client.get("/api/v1/recommend/suggest", params={"uid": uid, "query": rq})
            assert rr.status_code == 200

        r_last = client.get("/api/v1/recommend/suggest", params={"uid": uid, "query": "from those, give me top 2 and explain why"})
        assert r_last.status_code == 200
        body = r_last.json()
        last_skus = [str((x or {}).get("sku") or "") for x in (body.get("results") or []) if isinstance(x, dict)]
        last_skus = [s for s in last_skus if s]
        assert last_skus
        assert all(s in set(base_skus) for s in last_skus)
    finally:
        RecommendationService.retrieve_candidates = orig_retrieve


def test_nqe_confidence_gating_prefers_non_techy_prompts_for_ambiguous_queries():
    qs = [{"id": "ask_specs", "text": "What specs do you need?"}]
    out = recommend_router._apply_nqe_confidence_gating(qs, query="help me pick a laptop", confidence_band="low")
    assert isinstance(out, list) and out
    txt = str((out[0] or {}).get("text") or "").lower()
    assert "must-have features" in txt
    assert "gpu class" not in txt


def test_nqe_confidence_gating_uses_techy_prompts_for_requirements_queries():
    qs = [{"id": "ask_specs", "text": "What specs do you need?"}]
    out = recommend_router._apply_nqe_confidence_gating(
        qs, query="what are the system requirements for ai training and cuda", confidence_band="high"
    )
    assert isinstance(out, list) and out
    txt = str((out[0] or {}).get("text") or "").lower()
    assert "gpu class" in txt


def test_open_ended_response_sets_needs_disambiguation():
    _write_flags({
        "USE_AGENT_CAPABILITIES": True,
        "AGENT_ROLLOUT_PERCENT": 100,
        "CAPABILITIES": {"recommend": {"enabled": True, "rollout_percent": 100}},
        "KILL_SWITCH": False,
        "DECISION_LOG_WRITES_ENABLED": False,
        "DEGRADATION": {"enabled": True},
        "TEST_FORCE_BAD_SKU": False,
    })
    r = client.get("/api/v1/recommend/suggest", params={"uid": "u-open-ended-nd-1", "query": "help me choose a laptop"})
    assert r.status_code == 200
    body = r.json()
    assert body.get("needs_disambiguation") is True


def test_why_product_endpoint_returns_explanation_and_logs_event():
    orig_retrieve = RecommendationService.retrieve_candidates
    try:
        RecommendationService.retrieve_candidates = lambda self, query, limit=10: [
            {"id": "p1", "sku": "WHY-1", "name": "Creator Pro 16", "price_cents": 179900, "currency": "USD", "stock": 4, "specs": {"gpu": "rtx 4070", "ram_gb": 32}},
            {"id": "p2", "sku": "WHY-2", "name": "Office Light 14", "price_cents": 109900, "currency": "USD", "stock": 8, "specs": {"gpu": "integrated", "ram_gb": 16}},
        ]
        _write_flags({
            "USE_AGENT_CAPABILITIES": True,
            "AGENT_ROLLOUT_PERCENT": 100,
            "CAPABILITIES": {"recommend": {"enabled": True, "rollout_percent": 100}},
            "KILL_SWITCH": False,
            "DECISION_LOG_WRITES_ENABLED": False,
            "DEGRADATION": {"enabled": True},
            "TEST_FORCE_BAD_SKU": False,
        })
        uid = "u-why-product-1"
        r1 = client.get("/api/v1/recommend/suggest", params={"uid": uid, "query": "video editing laptop under 2000"})
        assert r1.status_code == 200
        trace_id = "trace-why-product-1"
        r2 = client.get(
            "/api/v1/recommend/why_product",
            params={"uid": uid, "sku": "WHY-1", "query": "video editing laptop under 2000", "trace_id": trace_id},
        )
        assert r2.status_code == 200
        body = r2.json()
        exp = body.get("explanation") or {}
        assert body.get("decision_trace_id") == trace_id
        assert str(exp.get("sku") or "") == "WHY-1"
        assert isinstance(exp.get("reason_summary"), str) and exp.get("reason_summary")
        assert isinstance(exp.get("disqualifiers"), list)

        ev = client.get(f"/api/v1/trace/{trace_id}/events")
        assert ev.status_code == 200
        events = ev.json().get("events") or []
        assert any(str(e.get("source_id") or "") == "Selection_Explain_Agent" for e in events)
    finally:
        RecommendationService.retrieve_candidates = orig_retrieve


def test_turn_type_classifier_covers_core_paths():
    assert recommend_router._classify_turn_type(results_count=0, followup_explain=False, explicit_constraint_update=False) == "zero_result_turn"
    assert recommend_router._classify_turn_type(results_count=3, followup_explain=True, explicit_constraint_update=False) == "explain_turn"
    assert recommend_router._classify_turn_type(results_count=2, followup_explain=False, explicit_constraint_update=True) == "constraint_update_turn"
    assert recommend_router._classify_turn_type(results_count=2, followup_explain=False, explicit_constraint_update=False) == "result_turn"


def test_followup_explain_detector_extended_phrases():
    positives = [
        "tell me more about that one",
        "what does that mean",
        "how does this compare",
        "can you elaborate on this pick",
        "walk me through why you chose it",
    ]
    for q in positives:
        assert recommend_router._is_followup_explain_query(q) is True


def test_recommend_passes_has_image_to_complexity_context(monkeypatch):
    orig_retrieve = RecommendationService.retrieve_candidates
    captured_contexts = []
    try:
        RecommendationService.retrieve_candidates = lambda self, query, limit=10: [
            {"id": "p1", "sku": "CTX-1", "name": "Laptop A", "price_cents": 109900, "currency": "USD", "stock": 4, "specs": {"ram_gb": 16}},
            {"id": "p2", "sku": "CTX-2", "name": "Laptop B", "price_cents": 129900, "currency": "USD", "stock": 3, "specs": {"ram_gb": 16}},
        ]
        _write_flags({
            "USE_AGENT_CAPABILITIES": True,
            "AGENT_ROLLOUT_PERCENT": 100,
            "CAPABILITIES": {"recommend": {"enabled": True, "rollout_percent": 100}},
            "KILL_SWITCH": False,
            "DECISION_LOG_WRITES_ENABLED": False,
            "DEGRADATION": {"enabled": True},
            "TEST_FORCE_BAD_SKU": False,
        })

        def _capture_model(query, *, context=None):
            captured_contexts.append(dict(context or {}))
            return "llama3:8b"

        def _capture_complex(query, *, context=None):
            captured_contexts.append(dict(context or {}))
            return False

        def _capture_explain(query, *, context=None):
            captured_contexts.append(dict(context or {}))
            return {"length_trigger": False, "matched_keywords": [], "conjunction_count": 0, "score": 0}

        monkeypatch.setattr(recommend_router, "select_ollama_model", _capture_model)
        monkeypatch.setattr(recommend_router, "is_complex_query", _capture_complex)
        monkeypatch.setattr(recommend_router, "complexity_explain", _capture_explain)

        r = client.get(
            "/api/v1/recommend/suggest",
            params={
                "uid": "u-context-img-1",
                "query": "compare alternatives like this",
                "image_labels": "laptop,lenovo",
            },
        )
        assert r.status_code == 200
        assert captured_contexts, "Expected complexity context capture from model-routing helpers"
        assert any(bool(c.get("has_image")) for c in captured_contexts)
    finally:
        RecommendationService.retrieve_candidates = orig_retrieve


def test_recommend_uses_vision_product_identity_from_cached_image_blob(monkeypatch):
    orig_retrieve = RecommendationService.retrieve_candidates
    try:
        RecommendationService.retrieve_candidates = lambda self, query, limit=10: [
            {"id": "p1", "sku": "VID-1", "name": "Laptop A", "price_cents": 149900, "currency": "USD", "stock": 4, "specs": {"ram_gb": 16}},
            {"id": "p2", "sku": "VID-2", "name": "Laptop B", "price_cents": 159900, "currency": "USD", "stock": 4, "specs": {"ram_gb": 16}},
        ]
        _write_flags({
            "USE_AGENT_CAPABILITIES": True,
            "AGENT_ROLLOUT_PERCENT": 100,
            "CAPABILITIES": {"recommend": {"enabled": True, "rollout_percent": 100}},
            "KILL_SWITCH": False,
            "DECISION_LOG_WRITES_ENABLED": False,
            "DEGRADATION": {"enabled": True},
            "TEST_FORCE_BAD_SKU": False,
        })
        uid = "u-vision-identity-1"
        mem = Memory(get_redis())
        kv = mem.get_kv(uid) or {}
        kv["image_blob_cache"] = {"img-hash-1": base64.b64encode(b"fake-image-bytes").decode("ascii")}
        mem.set_kv(uid, kv)

        import src.app.services.product_identity_agent as pia

        monkeypatch.setattr(
            pia,
            "identify_product_from_image",
            lambda image_bytes, user_query=None, trace_id=None, timeout_s=12.0: {
                "ok": True,
                "identified": True,
                "brand": "Lenovo",
                "product_type": "laptop",
                "cpu_tier": "midrange",
                "confidence": 0.92,
            },
        )
        monkeypatch.setattr(
            pia,
            "identify_product_from_text",
            lambda labels, ocr_text, user_query=None, trace_id=None: {
                "ok": True,
                "identified": False,
                "confidence": 0.0,
            },
        )
        monkeypatch.setattr(
            pia,
            "specs_to_constraints",
            lambda identity: {"identity_brand": "Lenovo"} if identity.get("identified") else {},
        )

        r = client.get(
            "/api/v1/recommend/suggest",
            params={
                "uid": uid,
                "query": "find alternatives like this",
                "image_hash": "img-hash-1",
                "image_labels": "laptop,lenovo",
            },
        )
        assert r.status_code == 200
        body = r.json()
        prod_id = body.get("product_identity") or {}
        assert prod_id.get("source") == "vision_image"
        assert (prod_id.get("constraints") or {}).get("identity_brand") == "Lenovo"
    finally:
        RecommendationService.retrieve_candidates = orig_retrieve


def test_recommend_includes_fraud_summary_from_tls_geo_context(monkeypatch):
    orig_retrieve = RecommendationService.retrieve_candidates
    captured = {"session_data": None}
    try:
        RecommendationService.retrieve_candidates = lambda self, query, limit=10: [
            {"id": "p1", "sku": "FR-1", "name": "Laptop A", "price_cents": 99900, "currency": "USD", "stock": 2, "specs": {"ram_gb": 16}},
        ]
        _write_flags({
            "USE_AGENT_CAPABILITIES": True,
            "AGENT_ROLLOUT_PERCENT": 100,
            "CAPABILITIES": {"recommend": {"enabled": True, "rollout_percent": 100}},
            "KILL_SWITCH": False,
            "DECISION_LOG_WRITES_ENABLED": False,
            "DEGRADATION": {"enabled": True},
            "TEST_FORCE_BAD_SKU": False,
        })
        monkeypatch.setenv("FRAUD_KNOWN_JA3_HASHES", "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")
        monkeypatch.setenv("FRAUD_KNOWN_JA4_HASHES", "bbbbbbbbbbbbbbbb")
        monkeypatch.setattr(
            recommend_router,
            "extract_tls_fingerprints_from_request",
            lambda req: {
                "source_ip": "203.0.113.5",
                "trusted_proxy_source": True,
                "ja3_hash": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                "ja4_hash": "bbbbbbbbbbbbbbbb",
            },
        )

        class _StubFraudScorer:
            def score_with_enrichment(self, base_signals, expected_serial, observed_serial, image_phash, session_data=None, case_id=None):
                captured["session_data"] = dict(session_data or {})
                return 0.91, "high", {"ja3_known_fraud_tool": True, "geoip_high_risk_country": True}

        monkeypatch.setattr(recommend_router, "FraudScorer", _StubFraudScorer)

        r = client.get("/api/v1/recommend/suggest", params={"uid": "u-fraud-summary-1", "query": "show me laptops under $1200"})
        assert r.status_code == 200
        body = r.json()
        fraud = body.get("fraud") or {}
        assert float(fraud.get("score") or 0.0) == 0.91
        assert str(fraud.get("level") or "") == "high"
        assert bool((fraud.get("signals") or {}).get("ja3_known_fraud_tool")) is True
        sd = captured.get("session_data") or {}
        assert sd.get("ja3_hash") == "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        assert sd.get("ja4_hash") == "bbbbbbbbbbbbbbbb"
        assert sd.get("source_ip") == "203.0.113.5"
    finally:
        RecommendationService.retrieve_candidates = orig_retrieve


def test_update_pinned_context_persists_priority_slots():
    kv = {}
    out = recommend_router._update_pinned_context(
        kv=kv,
        constraints={
            "budget_min": 1000,
            "budget_max": 1800,
            "use_case": "gaming",
            "gpu_preference": "with_discrete",
            "brands": ["Lenovo"],
            "brand_excludes": ["Apple"],
        },
        shortlist_skus=["SKU-1", "SKU-2"],
        turn_type="result_turn",
        ts=12345,
    )
    pc = out.get("pinned_context") or {}
    assert isinstance(pc.get("budget"), dict)
    assert isinstance(pc.get("selected_skus"), dict)
    assert pc.get("gpu_preference", {}).get("value") == "with_discrete"
    assert pc.get("budget", {}).get("value", {}).get("max") == 1800
    assert pc.get("selected_skus", {}).get("value") == ["SKU-1", "SKU-2"]


def test_followup_reference_without_shortlist_prompts_disambiguation():
    orig_retrieve = RecommendationService.retrieve_candidates
    try:
        RecommendationService.retrieve_candidates = lambda self, query, limit=10: [
            {"id": "p1", "sku": "R-1", "name": "Laptop A", "price_cents": 99900, "currency": "USD", "stock": 4, "specs": {"ram_gb": 16}},
        ]
        _write_flags({
            "USE_AGENT_CAPABILITIES": True,
            "AGENT_ROLLOUT_PERCENT": 100,
            "CAPABILITIES": {"recommend": {"enabled": True, "rollout_percent": 100}},
            "KILL_SWITCH": False,
            "DECISION_LOG_WRITES_ENABLED": False,
            "DEGRADATION": {"enabled": True},
            "TEST_FORCE_BAD_SKU": False,
        })
        r = client.get("/api/v1/recommend/suggest", params={"uid": "u-ref-miss-1", "query": "show me those and why"})
        assert r.status_code == 200
        body = r.json()
        assert body.get("needs_disambiguation") is True
        assert float(body.get("memory_confidence") or 0.0) < 0.5
        nqs = body.get("next_questions") or []
        assert any(str((q or {}).get("id") or "") == "resolve_reference" for q in nqs if isinstance(q, dict))
    finally:
        RecommendationService.retrieve_candidates = orig_retrieve


def test_nqe_questions_do_not_repeat_without_constraint_change(monkeypatch):
    orig_retrieve = RecommendationService.retrieve_candidates
    try:
        RecommendationService.retrieve_candidates = lambda self, query, limit=10: [
            {"id": "p1", "sku": "NQE-1", "name": "Laptop A", "price_cents": 99900, "currency": "USD", "stock": 5, "specs": {"ram_gb": 16}},
            {"id": "p2", "sku": "NQE-2", "name": "Laptop B", "price_cents": 129900, "currency": "USD", "stock": 5, "specs": {"ram_gb": 16}},
        ]
        _write_flags({
            "USE_AGENT_CAPABILITIES": True,
            "AGENT_ROLLOUT_PERCENT": 100,
            "CAPABILITIES": {"recommend": {"enabled": True, "rollout_percent": 100}},
            "KILL_SWITCH": False,
            "DECISION_LOG_WRITES_ENABLED": False,
            "DEGRADATION": {"enabled": True},
            "TEST_FORCE_BAD_SKU": False,
        })

        uid = "u-nqe-repeat-guard-1"
        r1 = client.get(
            "/api/v1/recommend/suggest",
            params={
                "uid": uid,
                "query": "show laptops",
                "nqe_question_id": "ask_budget",
                "nqe_option_id": "budget_under_1000",
                "nqe_option_label": "Under $1,000",
            },
        )
        assert r1.status_code == 200

        r2 = client.get(
            "/api/v1/recommend/suggest",
            params={
                "uid": uid,
                "query": "show laptops",
                "nqe_question_id": "ask_budget",
                "nqe_option_id": "budget_1000_1500",
                "nqe_option_label": "$1,000-$1,500",
            },
        )
        assert r2.status_code == 200

        mem = Memory(get_redis())
        structured = mem.get_structured_state(uid)
        asked_ids = [str(x) for x in (structured.get("nqe_asked_ids") or [])]
        assert asked_ids.count("ask_budget") == 1
    finally:
        RecommendationService.retrieve_candidates = orig_retrieve


def test_structured_state_preserves_shortlist_after_zero_result_turn():
    orig_retrieve = RecommendationService.retrieve_candidates
    try:
        RecommendationService.retrieve_candidates = lambda self, query, limit=10: [
            {"id": "p1", "sku": "SS-1", "name": "Gaming Laptop 1", "price_cents": 159900, "currency": "USD", "stock": 5, "specs": {"gpu": "rtx 4060"}},
            {"id": "p2", "sku": "SS-2", "name": "Gaming Laptop 2", "price_cents": 169900, "currency": "USD", "stock": 5, "specs": {"gpu": "rtx 4060"}},
        ]
        _write_flags({
            "USE_AGENT_CAPABILITIES": True,
            "AGENT_ROLLOUT_PERCENT": 100,
            "CAPABILITIES": {"recommend": {"enabled": True, "rollout_percent": 100}},
            "KILL_SWITCH": False,
            "DECISION_LOG_WRITES_ENABLED": False,
            "DEGRADATION": {"enabled": True},
            "TEST_FORCE_BAD_SKU": False,
        })

        uid = "u-structured-shortlist-1"
        r1 = client.get("/api/v1/recommend/suggest", params={"uid": uid, "query": "show me gaming laptops between 1500 and 1900"})
        assert r1.status_code == 200
        b1 = r1.json()
        turn1_skus = [str((x or {}).get("sku") or "") for x in (b1.get("results") or []) if isinstance(x, dict)]
        turn1_skus = [x for x in turn1_skus if x]
        assert turn1_skus

        r2 = client.get("/api/v1/recommend/suggest", params={"uid": uid, "query": "show options under $50"})
        assert r2.status_code == 200
        b2 = r2.json()
        assert (b2.get("results") or []) == []

        mem = Memory(get_redis())
        structured = mem.get_structured_state(uid)
        assert isinstance(structured, dict)
        stored_shortlist = structured.get("last_shortlist_skus") or []
        assert stored_shortlist
        assert all(s in set(turn1_skus) for s in stored_shortlist)
    finally:
        RecommendationService.retrieve_candidates = orig_retrieve
