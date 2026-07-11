"""apply_cart_ops (V2 cart milestone step 2) — executes a resolved plan by REUSING the guarded,
stock-gated cart handlers (never a second copy of the stock/sourcing gate).

Proves the compound-edit screenshot end to end (remove two + set one to N) plus the stock gate,
the allow_sourcing shortfall path, keep_only, clear_all, and clear_previous (carried-set)."""
import pathlib
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from src.app.routers.cart import CartItemPayload, add_item, apply_cart_ops
from src.app.security.auth import ROLE_OWNER
from src.app.services.recommendation_core.cart_resolver import CartOp


def _make_engine():
    eng = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False},
                        poolclass=StaticPool, future=True)
    schema_path = pathlib.Path("db/schema.sql")
    if schema_path.exists():
        with eng.connect() as conn:
            for stmt in [s.strip() for s in schema_path.read_text(encoding="utf-8").split(";") if s.strip()]:
                try:
                    conn.execute(text(stmt))
                except Exception:
                    pass
            conn.commit()
    else:
        import src.app.models.db as _dbmod
        _dbmod._ensure_minimal_sqlite_tables(eng)
    return eng


def _seed(eng, rows):
    with eng.connect() as conn:
        for p in rows:
            pid = str(uuid.uuid4())
            conn.execute(text("INSERT OR IGNORE INTO products (id, sku, name, price_cents, active) "
                              "VALUES (:id, :sku, :name, :price, 1)"),
                         {"id": pid, "sku": p["sku"], "name": p["name"], "price": p.get("price_cents", 10000)})
            if int(p.get("stock", 0)) > 0:
                conn.execute(text("INSERT INTO inventory (id, product_id, stock, warehouse) "
                                  "VALUES (:id, :pid, :stock, 'default')"),
                             {"id": str(uuid.uuid4()), "pid": pid, "stock": int(p["stock"])})
        conn.commit()


@pytest.fixture()
def wired(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    eng = _make_engine()
    import src.app.models.db as _dbmod
    orig = _dbmod.engine
    _dbmod.engine = eng
    try:
        _dbmod.set_engine(eng)
    except Exception:
        pass
    _seed(eng, [
        {"sku": "SKU-ENVY", "name": "HP Envy x360 14", "stock": 100},
        {"sku": "SKU-TPAD", "name": "Lenovo ThinkPad L13", "stock": 100},
        {"sku": "SKU-IDEA", "name": "Lenovo IdeaPad Slim 3i", "stock": 100},
        {"sku": "SKU-LOW", "name": "Scarce Widget", "stock": 5},
    ])
    yield eng
    _dbmod.engine = orig
    try:
        _dbmod.set_engine(orig)
    except Exception:
        pass


def _add(uid, sku, qty):
    add_item(CartItemPayload(uid=uid, sku=sku, quantity=qty), role=ROLE_OWNER)


def _skus(result):
    return {it["sku"] for it in result["cart"].get("items", [])}


def _qty(result, sku):
    return next((int(it["quantity"]) for it in result["cart"].get("items", []) if it["sku"] == sku), None)


# ── the compound-edit screenshot, executed ───────────────────────────────────────

def test_compound_edit_executes(wired):
    uid = "u-compound"
    _add(uid, "SKU-ENVY", 1)
    _add(uid, "SKU-TPAD", 30)
    _add(uid, "SKU-IDEA", 1)
    ops = [
        CartOp(action="remove_items", target_skus=("SKU-ENVY", "SKU-TPAD")),
        CartOp(action="set_quantity", target_skus=("SKU-IDEA",), quantity=20),
    ]
    result = apply_cart_ops(uid, ops, role=ROLE_OWNER)
    assert _skus(result) == {"SKU-IDEA"}
    assert _qty(result, "SKU-IDEA") == 20
    assert not result["rejected"]


# ── individual ops ────────────────────────────────────────────────────────────────

def test_remove_items(wired):
    uid = "u-rm"
    _add(uid, "SKU-ENVY", 1)
    _add(uid, "SKU-IDEA", 1)
    result = apply_cart_ops(uid, [CartOp(action="remove_items", target_skus=("SKU-ENVY",))], role=ROLE_OWNER)
    assert _skus(result) == {"SKU-IDEA"}


def test_clear_all(wired):
    uid = "u-clear"
    _add(uid, "SKU-ENVY", 1)
    _add(uid, "SKU-IDEA", 1)
    result = apply_cart_ops(uid, [CartOp(action="clear_all")], role=ROLE_OWNER)
    assert _skus(result) == set()


def test_keep_only(wired):
    uid = "u-keep"
    _add(uid, "SKU-ENVY", 1)
    _add(uid, "SKU-TPAD", 1)
    _add(uid, "SKU-IDEA", 1)
    result = apply_cart_ops(uid, [CartOp(action="keep_only", target_skus=("SKU-TPAD",))], role=ROLE_OWNER)
    assert _skus(result) == {"SKU-TPAD"}


def test_set_quantity_in_stock(wired):
    uid = "u-setq"
    _add(uid, "SKU-IDEA", 1)
    result = apply_cart_ops(uid, [CartOp(action="set_quantity", target_skus=("SKU-IDEA",), quantity=7)], role=ROLE_OWNER)
    assert _qty(result, "SKU-IDEA") == 7


# ── the stock/sourcing gate is REUSED, not reimplemented ─────────────────────────

def test_set_quantity_over_stock_rejected_without_sourcing(wired):
    uid = "u-over"
    _add(uid, "SKU-LOW", 1)
    result = apply_cart_ops(uid, [CartOp(action="set_quantity", target_skus=("SKU-LOW",), quantity=50)], role=ROLE_OWNER)
    assert result["rejected"], "over-stock set_quantity must surface the handler's stock rejection"
    assert result["rejected"][0]["error"]["error"] in ("insufficient_stock", "out_of_stock")
    assert _qty(result, "SKU-LOW") == 1               # unchanged — not silently forced


def test_set_quantity_over_stock_sources_with_allow_sourcing(wired):
    uid = "u-source"
    _add(uid, "SKU-LOW", 1)
    result = apply_cart_ops(uid, [CartOp(action="set_quantity", target_skus=("SKU-LOW",), quantity=50)],
                            role=ROLE_OWNER, allow_sourcing=True)
    assert not result["rejected"]
    assert _qty(result, "SKU-LOW") == 50
    applied = result["applied"][0]
    assert applied.get("sourcing") and applied["sourcing"]["shortfall"] == 45


# ── clear_previous needs the carried set (never guess-and-wipe) ──────────────────

def test_clear_previous_with_carried_set(wired):
    uid = "u-prev"
    _add(uid, "SKU-ENVY", 1)   # "carried"
    _add(uid, "SKU-IDEA", 1)   # this-session
    result = apply_cart_ops(uid, [CartOp(action="clear_previous")], role=ROLE_OWNER, carried_skus=["SKU-ENVY"])
    assert _skus(result) == {"SKU-IDEA"}


def test_clear_previous_without_carried_set_is_rejected_not_wiped(wired):
    uid = "u-prev2"
    _add(uid, "SKU-ENVY", 1)
    _add(uid, "SKU-IDEA", 1)
    result = apply_cart_ops(uid, [CartOp(action="clear_previous")], role=ROLE_OWNER)
    assert _skus(result) == {"SKU-ENVY", "SKU-IDEA"}   # nothing wiped on a guess
    assert result["rejected"][0]["error"] == "no_carried_set"
