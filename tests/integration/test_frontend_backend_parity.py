"""Frontend ↔ backend parity gate — the foundation safety net.

Locks the per-product + response contract the FRONTEND renders (App.tsx /
ProductGrid.tsx / ChatOverlay.tsx) so attribution / hippograph / availability fields
cannot silently drift as the response grows.

ENDPOINT CHOICE: the frontend calls POST /api/v1/chat/query, but that handler makes an
internal HTTP self-call to /api/v1/recommend/suggest (chat.py:1628-1629,1741) — not
reachable from an in-process TestClient. chat.py then maps `results[] -> products[]`
1:1 and only *adds* price↔price_cents symmetry (chat.py:1859-1927). So this gate asserts
the SOURCE-OF-TRUTH `results[]` item contract via /recommend/suggest (reliable in CI);
the live /chat/query DOM render parity is covered by tests/pw/test_answer_first_parity.py.

Drift classes locked here (have bitten us or will):
  * price / price_cents — the "$0" rendering bug
  * stock_status enum   — unknown/None -> wrong badge / false "in stock"
  * cart_eligible       — null vs bool -> wrong Add-to-Cart gate
  * next_questions shape — strings vs {id,text,options:[{id,label}]} -> NQE render crash
  * trace_id            — App.tsx falls back across 5 names; if all absent the trace isn't clickable

OPERATING RULE: every NEW field the frontend renders (attribution, hippograph insight,
availability allocation, ...) gets an assertion ADDED HERE in the same PR that adds it.
Contract-shape only (no value assertions — those depend on LLM/seed/ranking and are flaky).
"""
from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from src.app.main import app
from src.app.models.db import db_session
from src.app.services.recommendations import RecommendationService
from tests.utils import default_headers
from tests.test_recommend import _write_flags

_FLAGS_PATH = os.path.join("config", "feature_flags.json")
# Deterministic product-path flags so the gate is order-independent (other test
# modules leave varying flag state in the global feature_flags.json).
_PRODUCT_PATH_FLAGS = {
    "USE_AGENT_CAPABILITIES": True,
    "AGENT_ROLLOUT_PERCENT": 100,
    "CAPABILITIES": {"recommend": {"enabled": True, "rollout_percent": 100}},
    "KILL_SWITCH": False,
    "DECISION_LOG_WRITES_ENABLED": False,
    "DEGRADATION": {"enabled": True},
    "TEST_FORCE_BAD_SKU": False,
}

client = TestClient(app, headers=default_headers())

# (sku, name, price_cents, stock) — FBP-3 is OOS to exercise the stock/cart gate.
_CATALOG = [
    ("FBP-1", "Dell Latitude 14 business laptop", 119900, 8),
    ("FBP-2", "Lenovo ThinkPad T14 work laptop", 149900, 5),
    ("FBP-3", "HP ProBook 450 office laptop", 99900, 0),
]
_VALID_STOCK = {"in_stock", "low_stock", "very_low_stock", "out_of_stock", None}


@pytest.fixture(scope="module", autouse=True)
def _seed():
    orig = RecommendationService.retrieve_candidates
    # Force the deterministic DB-fallback path so seeded products surface (same
    # technique as tests/acceptance/test_reference_query_matrix.py).
    RecommendationService.retrieve_candidates = lambda self, query, limit=10: []
    _orig_flags = open(_FLAGS_PATH, encoding="utf-8").read() if os.path.isfile(_FLAGS_PATH) else None
    _write_flags(_PRODUCT_PATH_FLAGS)
    _orig_narration = os.environ.get("RECOMMEND_NARRATION_MODE")
    os.environ["RECOMMEND_NARRATION_MODE"] = "skip"  # fast + deterministic
    with db_session() as db:
        for sku, name, cents, stock in _CATALOG:
            db.execute(text(
                "INSERT OR REPLACE INTO products (id, sku, name, price_cents, currency, specs, active) "
                "VALUES (:id,:sku,:n,:c,'USD',:s,1)"),
                # Rich specs so the products satisfy any use-case spec floors the pipeline may
                # enrich (e.g. storage_gb_min:256) regardless of test ordering — keeps the gate
                # order-independent.
                {"id": sku, "sku": sku, "n": name, "c": cents,
                 "s": '{"ram_gb": 16, "storage_gb": 1024, "display": "15.6 FHD"}'})
            db.execute(text(
                "INSERT OR REPLACE INTO inventory (id, product_id, stock, warehouse) "
                "VALUES (:i,:p,:st,'default')"), {"i": "inv-" + sku, "p": sku, "st": stock})
        db.commit()
    yield
    RecommendationService.retrieve_candidates = orig
    if _orig_narration is None:
        os.environ.pop("RECOMMEND_NARRATION_MODE", None)
    else:
        os.environ["RECOMMEND_NARRATION_MODE"] = _orig_narration
    if _orig_flags is not None:
        with open(_FLAGS_PATH, "w", encoding="utf-8") as f:
            f.write(_orig_flags)
    with db_session() as db:
        for sku, *_ in _CATALOG:
            db.execute(text("DELETE FROM inventory WHERE product_id=:p"), {"p": sku})
            db.execute(text("DELETE FROM products WHERE id=:p"), {"p": sku})
        db.commit()


def _suggest(uid: str, query: str) -> dict:
    r = client.get("/api/v1/recommend/suggest", params={"uid": uid, "query": query})
    assert r.status_code == 200, f"{uid}: HTTP {r.status_code} — {r.text[:400]}"
    body = r.json()
    assert isinstance(body, dict), f"{uid}: body is {type(body).__name__}"
    return body


def _items(body: dict) -> list:
    """The list chat.py maps 1:1 into the frontend's products[]."""
    out = body.get("results")
    return out if isinstance(out, list) else []


def _resolve_trace_id(body: dict) -> str | None:
    for k in ("decision_trace_id", "trace_id", "decision_id", "case_id"):
        v = body.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None


# ── Top-level response contract ──────────────────────────────────────────────
@pytest.mark.parametrize("i,query", [
    (0, "laptop for work under 1500"),
    (1, "thinkpad work laptop"),
    (2, "show me an office laptop"),
])
def test_top_level_contract(i, query):
    body = _suggest(f"fbp-top-{i}", query)
    assert isinstance(body.get("results"), list), "results must be a list"
    assert isinstance(body.get("next_questions") or [], list), "next_questions must be a list"
    # advisory-OFF fields must NOT appear unless their flag is enabled (operating rule).
    assert "hippograph_insights" not in body, "hippograph feedback must be flag-gated (absent by default)"
    assert "market_findings" not in body, "market intelligence must be flag-gated (absent by default)"
    assert "ranking_experiment" not in body, "live ranking nudge must be flag-gated (absent by default)"


# ── Per-product item contract (the fields the grid renders) ──────────────────
def test_product_item_contract():
    body = _suggest("fbp-items", "laptop for work under 1500")
    items = _items(body)
    assert items, f"expected seeded products to surface; got none: {str(body)[:300]}"
    for p in items:
        sku = p.get("sku")
        assert sku, "product missing sku"
        price, cents = p.get("price"), p.get("price_cents")
        assert price is not None or cents is not None, f"{sku}: no price and no price_cents"
        # price ↔ price_cents symmetry — the "$0" bug class (chat.py reconciles both).
        if price is not None and cents is not None:
            assert abs(int(round(float(price) * 100)) - int(cents)) <= 1, (
                f"{sku}: price {price} inconsistent with price_cents {cents}")
        assert p.get("stock_status") in _VALID_STOCK, f"{sku}: invalid stock_status {p.get('stock_status')!r}"
        ce = p.get("cart_eligible")
        assert ce is None or isinstance(ce, bool), f"{sku}: cart_eligible not bool|None ({ce!r})"


def test_trace_id_always_resolvable():
    # The spine guarantees trace_id; the frontend's 5-name fallback must resolve it.
    body = _suggest("fbp-trace", "laptop for work under 1500")
    assert _resolve_trace_id(body), "no resolvable trace_id (App.tsx normalizeTraceId would fail)"


# ── next_questions option contract ───────────────────────────────────────────
def test_next_questions_option_shape():
    body = _suggest("fbp-nqe", "help me choose a laptop")
    for q in (body.get("next_questions") or []):
        assert q.get("id") and q.get("text"), f"malformed next_question: {q}"
        for opt in (q.get("options") or []):
            assert opt.get("id") and ("label" in opt), f"malformed option: {opt}"


# ── E0 attribution capture: a success turn records its decision ──────────────
def test_e0_capture_records_decision_row():
    from src.app.services import attribution
    body = _suggest("fbp-e0", "a good laptop under 1500")
    tid = body.get("trace_id")
    assert tid, "no trace_id on response"
    if not _items(body):
        import pytest as _pt
        _pt.skip("no products surfaced this run; E0 captures on the success path")
    with db_session() as adb:
        attribution.ensure_tables(adb)
        row = adb.execute(
            text("SELECT skus_json FROM recommendation_decision "
                 "WHERE trace_id = :t ORDER BY created_at DESC LIMIT 1"),
            {"t": tid},
        ).fetchone()
    assert row, "E0 should have recorded a recommendation_decision row for this trace_id"


# ── Stock honesty: an OOS item must not be cart-eligible ──────────────────────
def test_oos_product_not_cart_eligible():
    body = _suggest("fbp-oos", "office laptop")
    for p in _items(body):
        if p.get("stock_status") == "out_of_stock":
            assert p.get("cart_eligible") is not True, (
                f"{p.get('sku')}: out_of_stock but cart_eligible=True — contradictory stock gate")
