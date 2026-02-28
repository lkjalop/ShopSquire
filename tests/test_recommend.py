import json
import os
from tests.utils import default_headers
from sqlalchemy import text

from fastapi.testclient import TestClient
from src.app.main import create_app
from src.app.services.recommendations import RecommendationService
from src.app.models.db import db_session
from src.app.routers import recommend as recommend_router


app = create_app()

client = TestClient(app, headers=default_headers())


def _write_flags(flags: dict):
    path = os.path.join("config", "feature_flags.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(flags, f, ensure_ascii=False, indent=2)


def test_recommend_blocks_invalid_sku_output():
    orig_retrieve = RecommendationService.retrieve_candidates
    try:
        RecommendationService.retrieve_candidates = lambda self, query, limit=10: [
            {"id": "p1", "sku": "SKU1", "name": "Test Product", "price_cents": 1000, "currency": "USD", "stock": 5}
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
            {"id": "p1", "sku": "SKU1", "name": "Test Product", "price_cents": 1000, "currency": "USD", "stock": 5}
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
            {"id": "p1", "sku": "SKU1", "name": "Test Product", "price_cents": 1000, "currency": "USD", "stock": 5}
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
        assert body.get("status") == "review_required"
        assert body.get("approval_id")
        esc = body.get("escalation") or {}
        assert esc.get("reason") == "insufficient_stock_bulk"
        assert esc.get("approval_required") is True
        assert esc.get("approval_id") == body.get("approval_id")
        assert (esc.get("tags") or []).count("inventory_insufficient_stock") >= 1
        assert (esc.get("playbook_hint") or {}).get("id") == "PB-INV-004"
        trace_id = body.get("trace_id") or body.get("decision_trace_id")
        assert trace_id
        ev = client.get(f"/api/v1/trace/{trace_id}/events")
        assert ev.status_code == 200
        events = ev.json().get("events") or []
        assert any(
            e.get("event_type") == "handoff_requested"
            and e.get("source_id") == "Inventory_Agent"
            and e.get("target_id") == "Sales_Agent"
            for e in events
        )
        # Approval should show up in the pending queue.
        pend = client.get("/api/v1/approvals/pending")
        assert pend.status_code == 200
        pending = pend.json().get("pending") or []
        assert any(p.get("id") == body.get("approval_id") for p in pending)
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
            {"id": "p1", "sku": "SKU1500", "name": "Gaming A", "price_cents": 150000, "currency": "USD", "stock": 5},
            {"id": "p2", "sku": "SKU1700", "name": "Gaming B", "price_cents": 170000, "currency": "USD", "stock": 5},
            {"id": "p3", "sku": "SKU1800", "name": "Gaming C", "price_cents": 180000, "currency": "USD", "stock": 5},
            {"id": "p4", "sku": "SKU900", "name": "Office D", "price_cents": 90000, "currency": "USD", "stock": 5},
            {"id": "p5", "sku": "SKU1000", "name": "Office E", "price_cents": 100000, "currency": "USD", "stock": 5},
        ]
        uid = "u-followup-lock-1"
        r1 = client.get(
            "/api/v1/recommend/suggest",
            params={"uid": uid, "query": "show me portable gaming laptops between 1500 and 1900"},
        )
        assert r1.status_code == 200
        b1 = r1.json()
        n1 = len(b1.get("results") or [])
        assert n1 > 0

        r2 = client.get(
            "/api/v1/recommend/suggest",
            params={"uid": uid, "query": "can i get a detailed list? also tell me why this laptops?"},
        )
        assert r2.status_code == 200
        b2 = r2.json()
        n2 = len(b2.get("results") or [])
        assert n2 <= n1

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
            {"id": "p1", "sku": "SKU1", "name": "Lenovo Legion Pro 7 Laptop", "price_cents": 189900, "currency": "USD", "stock": 7, "specs": {"gpu": "rtx", "ram": "32gb"}},
            {"id": "p2", "sku": "SKU2", "name": "Dell XPS 15 Laptop", "price_cents": 199900, "currency": "USD", "stock": 4, "specs": {"gpu": "rtx", "ram": "32gb"}},
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
            "compare gaming laptops for AI/ML training and CUDA workflows, explain tradeoffs between "
            "thermals, VRAM, and battery life, and justify which one is better for long model training sessions under $2200"
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

