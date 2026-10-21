"""Frontend ↔ backend parity gate — the foundation safety net.

Locks the per-product + response contract the FRONTEND renders (App.tsx /
ProductGrid.tsx / ChatOverlay.tsx) so attribution / hippograph / availability fields
cannot silently drift as the response grows.

ENDPOINT CHOICE: the frontend calls POST /api/v1/chat/query, which delegates
in process to the V2 recommendation compatibility boundary. This gate checks
its source results contract directly; ordinary chat and DOM behavior have
separate browser gates.

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

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import text

from src.app.main import create_app
from src.app.models.db import create_runtime_engine, db_session, get_engine, set_engine
from src.app.models.database_ownership import database_owner
from tests.utils import default_headers, write_feature_flags
from tests.v2_catalog_fixture import grounded_v2_catalog

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

# (sku, name, price_cents, stock) — FBP-3 is OOS to exercise the stock/cart gate.
_CATALOG = [
    ("FBP-1", "Dell Latitude 14 business laptop", 119900, 8,
     {"ram_gb": 16, "storage_gb": 1024, "display": "15.6 FHD"}),
    ("FBP-2", "Lenovo ThinkPad T14 work laptop", 149900, 5,
     {"ram_gb": 16, "storage_gb": 1024, "display": "15.6 FHD"}),
    ("FBP-3", "HP ProBook 450 office laptop", 99900, 0,
     {"ram_gb": 16, "storage_gb": 1024, "display": "15.6 FHD"}),
]
_VALID_STOCK = {"in_stock", "low_stock", "very_low_stock", "out_of_stock", None}


@pytest.fixture(scope="module", autouse=True)
def _seed(tmp_path_factory):
    original_engine = get_engine()
    directory = tmp_path_factory.mktemp("frontend-backend-parity")
    database_url = f"sqlite+pysqlite:///{directory / 'catalog.sqlite3'}"
    isolated_engine = create_runtime_engine(database_url)
    try:
        with pytest.MonkeyPatch.context() as patch:
            patch.setenv("DATABASE_URL", database_url)
            patch.setenv("DATABASE_URL_RO", database_url)
            patch.setenv("FEATURE_FLAGS_PATH", str(directory / "feature-flags.json"))
            patch.setenv("RECOMMEND_NARRATION_MODE", "skip")
            patch.setenv("USE_MOCK_LLM", "1")
            patch.setenv("TASK_ALLOW_INPROCESS_FALLBACK", "0")
            command.upgrade(Config("alembic.ini"), "head")
            set_engine(isolated_engine)
            write_feature_flags(_PRODUCT_PATH_FLAGS)
            with database_owner(isolated_engine):
                with grounded_v2_catalog(_CATALOG, node_handle="el-6-6", source="frontend_backend_parity"):
                    yield isolated_engine
    finally:
        set_engine(original_engine)
        isolated_engine.dispose()


@pytest.fixture(autouse=True)
def _contract_router(monkeypatch):
    # This suite checks seeded product serialization, not live intent inference.
    monkeypatch.setenv("RECOMMEND_CORE_MODE", "primary")
    monkeypatch.setattr(
        "src.app.services.recommendation_core.turn_router._default_llm_fn",
        lambda _prompt, _timeout: '{"lane":"SEARCH","handle":"el-6-6","confidence":0.9}',
    )


def _suggest(uid: str, query: str) -> dict:
    selected_engine = get_engine()
    app = create_app()
    created_engine = getattr(app.state, "engine", None)
    if getattr(app.state, "owns_engine", False) and created_engine is not selected_engine and created_engine is not None:
        created_engine.dispose()
    app.state.engine = selected_engine
    app.state.owns_engine = False
    with TestClient(app, headers=default_headers()) as client:
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
    assert "market_evidence" not in body, "structured market evidence must be flag-gated (absent by default)"
    assert "market_evidence_note" not in body, "narration evidence must be flag-gated (absent by default)"
    assert "ranking_experiment" not in body, "live ranking nudge must be flag-gated (absent by default)"
    assert "phrasing_experiment" not in body, "template phrasing must be flag-gated (absent by default)"
    assert "fulfillment_case" not in body, "procurement case creation must be flag-gated (absent by default)"


# ── Per-product item contract (the fields the grid renders) ──────────────────
def test_product_item_contract():
    # Keep this a catalog-contract query. A workload-qualified "for work"
    # request correctly requires external capability evidence and may return no
    # products, which is certified by the research gates instead.
    body = _suggest("fbp-items", "show me laptops under 1500")
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
