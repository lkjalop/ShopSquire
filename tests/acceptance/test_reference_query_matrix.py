"""Roadmap #3 — acceptance matrix over permutations of the two reference queries.

Runs many phrasings of the bulk-B2B and portable reference queries through the REAL route
(/api/v1/recommend/suggest) and asserts the query-understanding contracts agree end-to-end:
budget parsing (comma/plain/$/range/none), spec-units-are-not-budgets, bulk quantity (digit + word),
no-budget => empty within_budget bucket, never-blank, and escalation present for bulk B2B.

These are the contracts the GPT-5.5 live test + this session's fixes established; the matrix is the
regression net so a future edit can't silently reintroduce "$2 from 2kg", a missing quantity, or a
"within budget" claim with no budget.
"""
from __future__ import annotations

import json
import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from tests.utils import default_headers, write_feature_flags
from src.app.main import create_app
from src.app.models.db import db_session
from src.app.services.taxonomy_registry import add_sold_node, upsert_classification

_FLAGS_PATH = os.path.join("config", "feature_flags.json")
# Deterministic product-path flags so the matrix is robust to whatever flag state other test modules
# leave in the global feature_flags.json (otherwise order-dependent: a prior test setting
# AGENT_ROLLOUT_PERCENT=0 routes around the agent path → no order_quantity / price_buckets).
_PRODUCT_PATH_FLAGS = {
    "USE_AGENT_CAPABILITIES": True,
    "AGENT_ROLLOUT_PERCENT": 100,
    "CAPABILITIES": {"recommend": {"enabled": True, "rollout_percent": 100}},
    "KILL_SWITCH": False,
    "DECISION_LOG_WRITES_ENABLED": False,
    "DEGRADATION": {"enabled": True},
    "TEST_FORCE_BAD_SKU": False,
}

client = TestClient(create_app(), headers=default_headers())
_RUN_ID = uuid4().hex[:8]

_CATALOG = [
    ("MTX-APL", "Apple MacBook Air", 129900, 1.24),
    ("MTX-DEL", "Dell XPS 13", 119900, 1.20),
    ("MTX-LG", "LG Gram 17", 159900, 1.35),
    ("MTX-MSI", "MSI Katana 15", 149900, 2.90),
    ("MTX-HP", "HP Victus 16", 124900, 2.40),
]


@pytest.fixture(scope="module", autouse=True)
def _seed():
    # Pin product-path flags (save + restore) so the matrix is order-independent.
    _orig_flags = open(_FLAGS_PATH, encoding="utf-8").read() if os.path.isfile(_FLAGS_PATH) else None
    write_feature_flags(_PRODUCT_PATH_FLAGS)
    with db_session() as db:
        add_sold_node(db, node_handle="el-6-6", source="test")
        for sku, name, cents, wkg in _CATALOG:
            db.execute(text(
                "INSERT OR REPLACE INTO products (id, sku, name, price_cents, currency, specs, active) "
                "VALUES (:id,:sku,:name,:c,'AUD',:specs,1)"),
                {"id": sku, "sku": sku, "name": name, "c": cents,
                 "specs": f'{{"ram_gb": 16, "storage_gb": 1024, "weight_kg": {wkg}}}'})
            db.execute(text("INSERT OR REPLACE INTO inventory (id, product_id, stock, warehouse) "
                            "VALUES (:i,:p,8,'default')"), {"i": "inv-" + sku, "p": sku})
            upsert_classification(
                db,
                sku=sku,
                node_handle="el-6-6",
                source="test",
                status="approved",
                confidence=1.0,
            )
        db.commit()
    yield
    if _orig_flags is not None:
        with open(_FLAGS_PATH, "w", encoding="utf-8") as f:
            f.write(_orig_flags)
    with db_session() as db:
        for sku, *_ in _CATALOG:
            db.execute(text("DELETE FROM inventory WHERE product_id=:p"), {"p": sku})
            db.execute(text("DELETE FROM products WHERE id=:p"), {"p": sku})
        db.commit()


def _suggest(uid, query, **params):
    r = client.get(
        "/api/v1/recommend/suggest",
        params={"uid": f"{_RUN_ID}-{uid}", "query": query, **params},
    )
    assert r.status_code == 200, r.text
    return r.json()


def _cu(body):
    return body.get("constraints_used") or {}


# ── Budget parsing permutations ──────────────────────────────────────────────
@pytest.mark.parametrize("i,query,exp_max", [
    (0, "a laptop budget is $1,600", 1600),
    (1, "a laptop under $1,500", 1500),
    (2, "a laptop under 1500", 1500),
    (3, "a laptop with a budget of 1,200", 1200),
    (4, "a laptop", None),
])
def test_budget_parsing_matrix(i, query, exp_max):
    assert _cu(_suggest(f"mtx-b{i}", query)).get("budget_max") == exp_max


# ── Spec units are never budgets (the live Tier-0 finding) ───────────────────
@pytest.mark.parametrize("i,query", [
    (0, "a portable laptop under 2 kg"),
    (1, "a laptop under 2.5 kg"),
    (2, "a laptop with 16 gb under 2 kg"),
])
def test_units_never_become_budget(i, query):
    assert _cu(_suggest(f"mtx-u{i}", query)).get("budget_max") is None


# ── Bulk quantity (digit + word) + escalation present ────────────────────────
@pytest.mark.parametrize("i,query,exp_qty", [
    (0, "I need 10 laptops for business, budget is $1,600", 10),
    (1, "ten laptops for our team, budget 1500", 10),
    (2, "25 laptops for the company under $1,500", 25),
])
def test_bulk_quantity_and_escalation(i, query, exp_qty):
    body = _suggest(f"mtx-q{i}", query)
    assert _cu(body).get("order_quantity") == exp_qty
    assert isinstance(body.get("escalation_assessment"), dict)


# ── No budget => empty within_budget bucket; budget => non-empty ─────────────
def test_within_budget_bucket_only_with_budget():
    no_b = _suggest("mtx-nb", "a good laptop for university")
    assert (no_b.get("price_buckets") or {}).get("within_budget") in (None, [])
    with_b = _suggest("mtx-wb", "a good laptop under $1,500")
    pb = (with_b.get("price_buckets") or {}).get("within_budget") or []
    assert len(pb) >= 1  # products <= $1500 exist in the seeded catalog


# ── Never blank ──────────────────────────────────────────────────────────────
@pytest.mark.parametrize("i,query", [
    (0, "a laptop for university"),
    (1, "10 laptops for business under $1,600"),
    (2, "a portable laptop under 2 kg"),
])
def test_never_blank(i, query):
    body = _suggest(f"mtx-nbk{i}", query)
    # A useful response is products OR a message OR an explicit disambiguation/question request —
    # never a truly empty payload.
    useful = (
        (body.get("results") or [])
        or str(body.get("assistant_message") or "").strip()
        or (body.get("next_questions") or [])
        or body.get("needs_disambiguation")
    )
    assert useful, body


# ── Intent-aware B2B through the route (roadmap step 1, intent not a raw-quantity gate) ───────────
def _nq_ids(body):
    return [str((q or {}).get("id") or "") for q in (body.get("next_questions") or [])]


def test_business_bulk_surfaces_procurement_question_first():
    body = _suggest("mtx-b2b1", "10 laptops for the company under $1,500")
    assert "ask_b2b_procurement" in _nq_ids(body)
    ba = body.get("b2b_assessment") or {}
    assert ba.get("verdict") == "b2b" and ba.get("discount_eligible") is True


def test_ambiguous_bulk_surfaces_procurement_question_to_clarify():
    body = _suggest("mtx-b2b2", "I want 10 laptops under $1,500")
    assert "ask_b2b_procurement" in _nq_ids(body)
    assert (body.get("b2b_assessment") or {}).get("verdict") == "ambiguous_bulk"


def test_personal_multibuy_is_not_routed_b2b():
    body = _suggest("mtx-b2b3", "3 laptops for my family under $1,500")
    assert "ask_b2b_procurement" not in _nq_ids(body)
    assert (body.get("b2b_assessment") or {}).get("verdict") == "consumer"


def test_exact_compound_query_keeps_procurement_and_consistent_budget(monkeypatch):
    monkeypatch.setenv("RECOMMEND_NARRATION_MODE", "skip")
    query = (
        "I am thinking to buy 10 laptops for work in 2 weeks, "
        "what is good for 1300 to 1500? why those?"
    )
    body = _suggest(f"mtx-exact-compound-{uuid4().hex}", query)
    constraints = _cu(body)
    assert constraints.get("budget_min") == 1300
    assert constraints.get("budget_max") == 1500
    assert (constraints.get("slots") or {}).get("price_max") == 1500
    assert constraints.get("turn_intent") != "EXPLAIN"
    assert "ask_b2b_procurement" in _nq_ids(body)
    assert (body.get("b2b_assessment") or {}).get("verdict") == "ambiguous_bulk"
    escalation = body.get("escalation_assessment") or {}
    assert escalation.get("band") == "review"
    assert body.get("needs_human_review") is True
    # Commercial review is not a security incident. V2 keeps a traceable human
    # gate without fabricating incident authority.
    assert body.get("trace_id")
    assert body.get("incident_id") is None


def test_exact_compound_query_warm_latency_under_five_seconds(monkeypatch):
    monkeypatch.setenv("RECOMMEND_NARRATION_MODE", "skip")
    query = (
        "I am thinking to buy 10 laptops for work in 2 weeks, "
        "what is good for 1300 to 1500? why those?"
    )
    run_id = uuid4().hex
    _suggest(f"mtx-latency-warmup-{run_id}", query)
    samples = [
        _suggest(f"mtx-latency-{run_id}-{i}", query)
        for i in range(2)
    ]
    route_ms = [
        int((body.get("timing_breakdown") or {}).get("route_total_ms") or 999999)
        for body in samples
    ]
    assert max(route_ms) < 5000, route_ms
    assert all(
        (
            (body.get("timing_breakdown") or {}).get("compound_needed") is False
            or (body.get("timing_breakdown") or {}).get("compound_mode") == "skip"
        )
        for body in samples
    )


def test_portable_university_gaming_rationale_is_a_fresh_search(monkeypatch):
    monkeypatch.setenv("RECOMMEND_NARRATION_MODE", "skip")
    body = _suggest(
        f"mtx-portable-rationale-{uuid4().hex}",
        "I need something portable for university but good enough for gaming. "
        "Why are your picks suitable?",
    )
    constraints = _cu(body)
    assert constraints.get("turn_intent") != "EXPLAIN"
    assert {"student", "gaming"} <= set(constraints.get("use_case_tags") or [])
    assert (
        body.get("results")
        or body.get("next_questions")
        or str(body.get("assistant_message") or "").strip()
        or str(body.get("message") or "").strip()
    )
