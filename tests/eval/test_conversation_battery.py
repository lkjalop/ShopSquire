"""Conversation battery — the PARITY HARNESS for recommend.py extractions (and the nightly eval net).

Every probe encodes a behavior that BROKE in live demos and was fixed; each asserts the semantic
INVARIANT (qty parsed, budget honored, refusal present, lane not hijacked) rather than exact JSON, so
the battery survives cosmetic changes but fails on regressions. Rule: NO extraction pass on recommend.py
lands unless this file is green before AND after.

Single-turn probes only — multi-turn memory (floor-carry, cut-honored across turns) is covered by the
browser E2E (e2e/context-retention.spec.ts) where real Redis session state exists.
"""
from __future__ import annotations

import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from tests.utils import default_headers
from tests.test_recommend import _write_flags
from src.app.main import create_app
from src.app.models.db import db_session
from src.app.services.recommendations import RecommendationService

_FLAGS_PATH = os.path.join("config", "feature_flags.json")
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

_CATALOG = [
    ("BAT-A", "Aster Slim 14 Laptop", 119900, 1.2),
    ("BAT-B", "Boreal Pro 15 Laptop", 129900, 1.6),
    ("BAT-C", "Cinder Book 16 Laptop", 139900, 1.8),
    ("BAT-D", "Dune Air 13 Laptop", 99900, 1.1),
    ("BAT-E", "Ember Max 17 Laptop", 189900, 2.4),
]


@pytest.fixture(scope="module", autouse=True)
def _seed():
    orig = RecommendationService.retrieve_candidates
    RecommendationService.retrieve_candidates = lambda self, query, limit=10: []
    _orig_flags = open(_FLAGS_PATH, encoding="utf-8").read() if os.path.isfile(_FLAGS_PATH) else None
    _write_flags(_PRODUCT_PATH_FLAGS)
    with db_session() as db:
        for sku, name, cents, wkg in _CATALOG:
            db.execute(text(
                "INSERT OR REPLACE INTO products (id, sku, name, price_cents, currency, specs, active) "
                "VALUES (:id,:sku,:name,:c,'USD',:specs,1)"),
                {"id": sku, "sku": sku, "name": name, "c": cents,
                 "specs": f'{{"ram_gb": 16, "storage_gb": 512, "weight_kg": {wkg}}}'})
            db.execute(text("INSERT OR REPLACE INTO inventory (id, product_id, stock, warehouse) "
                            "VALUES (:i,:p,9,'default')"), {"i": "inv-" + sku, "p": sku})
        db.commit()
    yield
    RecommendationService.retrieve_candidates = orig
    if _orig_flags is not None:
        with open(_FLAGS_PATH, "w", encoding="utf-8") as f:
            f.write(_orig_flags)
    with db_session() as db:
        for sku, *_ in _CATALOG:
            db.execute(text("DELETE FROM inventory WHERE product_id=:p"), {"p": sku})
            db.execute(text("DELETE FROM products WHERE id=:p"), {"p": sku})
        db.commit()


def _suggest(query, **params):
    r = client.get("/api/v1/recommend/suggest",
                   params={"uid": f"bat-{uuid4().hex[:10]}", "query": query, **params})
    assert r.status_code == 200, r.text
    return r.json()


def _prices(body):
    return [float(x.get("price") or 0) for x in (body.get("results") or []) if x.get("price")]


# ── 1. bulk-qty phrasings: results MUST NOT zero out; the count lands in requested_quantity ────────
@pytest.mark.parametrize("query,qty", [
    ("can i get help with 15 work laptops. budget is 1000 to 1400? which to get?", 15),
    ("what laptops for work? budget 1000 to 1400, I need about 25", 25),
    ("can i get help with 30 or so laptops. for work. is 1000 to 1400 enough?", 30),
    ("bulk office laptops priced 1000 to 1400, need 18", 18),
])
def test_bulk_qty_returns_products_and_qty(query, qty):
    body = _suggest(query)
    assert len(body.get("results") or []) > 0, "bulk phrasing must never zero-out"
    assert body.get("requested_quantity") == qty


# ── 2. qty guards: model numbers and spec sizes are NEVER a quantity ───────────────────────────────
@pytest.mark.parametrize("query", ["dell 15 laptop under 1400", "15 inch laptops for work under 1400"])
def test_model_and_spec_numbers_are_not_quantities(query):
    body = _suggest(query)
    assert body.get("requested_quantity") in (None, 0)


# ── 3. budget grammar end-to-end (the five-parser class) ───────────────────────────────────────────
def test_budget_cut_revision_parses_as_ceiling():
    body = _suggest("cut it to 1300 max, work laptops")
    ps = _prices(body)
    assert ps, "cut phrasing must still return products"
    assert all(p <= 1300 * 1.001 for p in ps), f"cut ceiling violated: {ps}"


def test_grand_and_k_suffixes_parse():
    b1 = _suggest("work laptops under 2 grand")
    assert (b1.get("constraints_used") or {}).get("budget_max") == 2000
    b2 = _suggest("work laptops up to 1.5k")
    assert (b2.get("constraints_used") or {}).get("budget_max") == 1500


def test_spec_units_never_become_money():
    body = _suggest("work laptops under 2 kg")
    assert (body.get("constraints_used") or {}).get("budget_max") != 2


# ── 4. honest refusals (absurd qty + contradiction) ───────────────────────────────────────────────
def test_absurd_quantity_gets_honest_refusal_not_silence():
    body = _suggest("i need 99999 laptops tomorrow")
    note = str(body.get("refusal_note") or "")
    assert "1,000" in note or "1000" in note, f"refusal_note missing: {note!r}"


def test_contradiction_total_cap_gets_plain_words():
    body = _suggest("i want 50 laptops but keep the total under 5 grand")
    note = str(body.get("refusal_note") or "")
    assert "add up" in note.lower(), f"contradiction note missing: {note!r}"
    assert len(body.get("results") or []) > 0, "contradiction must not hide the products"


# ── 5. lane claim-checks (inventory + support hijacks) ─────────────────────────────────────────────
def test_purchase_phrasing_not_hijacked_by_inventory_lane():
    body = _suggest("can i get help with work laptops. budget is 1000 to 1400?")
    # the inventory lane's response shape has 'answer'/'source' and no results
    assert len(body.get("results") or []) > 0
    assert body.get("source") != "inventory_no_sku_match"


def test_presales_policy_question_is_not_a_support_claim():
    body = _suggest("gaming laptop under 1400. also what warranty do you offer?")
    cu = body.get("constraints_used") or {}
    assert str(cu.get("turn_intent") or "").upper() != "SUPPORT_CLAIM"
    assert len(body.get("results") or []) > 0


def test_broken_item_return_IS_a_support_claim():
    body = _suggest("how do i return a broken laptop i bought?")
    cu = body.get("constraints_used") or {}
    assert str(cu.get("turn_intent") or "").upper() == "SUPPORT_CLAIM"
