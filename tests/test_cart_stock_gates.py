"""Tests for cart stock gate correctness.

Covers:
  - POST /api/v1/cart/items: OOS rejection
  - POST /api/v1/cart/items: over-quantity rejection
  - POST /api/v1/cart/items: cumulative add cannot exceed stock
  - PUT /api/v1/cart/items: stock gate on full replace
  - PUT /api/v1/cart/items: duplicate SKUs aggregated before stock check
  - POST /api/v1/cart/voucher: disabled by default (feature flag)

All tests use an in-memory SQLite engine with products + inventory rows so
they run without a live Postgres or Redis dependency.
"""

import json
import os
import pathlib
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from tests.utils import default_headers

# ── App + engine helpers ──────────────────────────────────────────────────────

def _make_engine():
    eng = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    schema_path = pathlib.Path("db/schema.sql")
    if schema_path.exists():
        sql = schema_path.read_text(encoding="utf-8")
        with eng.connect() as conn:
            for stmt in [s.strip() for s in sql.split(";") if s.strip()]:
                try:
                    conn.execute(text(stmt))
                except Exception:
                    pass
            conn.commit()
    else:
        import src.app.models.db as _dbmod
        _dbmod._ensure_minimal_sqlite_tables(eng)
    return eng


def _seed(eng, products_and_stock: list[dict]) -> None:
    """Insert products + inventory rows.

    Each dict must have: sku, name, price_cents, stock (int).
    """
    with eng.connect() as conn:
        for p in products_and_stock:
            pid = str(uuid.uuid4())
            conn.execute(
                text(
                    "INSERT OR IGNORE INTO products (id, sku, name, price_cents, active) "
                    "VALUES (:id, :sku, :name, :price, 1)"
                ),
                {"id": pid, "sku": p["sku"], "name": p.get("name", p["sku"]), "price": p.get("price_cents", 10000)},
            )
            stock = int(p.get("stock", 0))
            if stock > 0:
                conn.execute(
                    text(
                        "INSERT INTO inventory (id, product_id, stock, warehouse) "
                        "VALUES (:id, :pid, :stock, 'default')"
                    ),
                    {"id": str(uuid.uuid4()), "pid": pid, "stock": stock},
                )
        conn.commit()


@pytest.fixture()
def client_with_stock(monkeypatch):
    """Return (TestClient, engine) with isolated DB seeded for stock tests."""
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("DISABLE_UI_ROUTES", "1")
    monkeypatch.setenv("VOUCHER_ENDPOINT_ENABLED", "0")

    eng = _make_engine()

    import src.app.models.db as _dbmod
    orig_engine = _dbmod.engine

    _dbmod.engine = eng
    try:
        _dbmod.set_engine(eng)
    except Exception:
        pass

    from src.app.main import create_app
    app = create_app()
    app.state.engine = eng

    _seed(eng, [
        {"sku": "SKU-INSTOCK-5",  "name": "In-Stock Widget",  "price_cents": 9900,  "stock": 5},
        {"sku": "SKU-INSTOCK-1",  "name": "Last Unit Widget",  "price_cents": 9900,  "stock": 1},
        {"sku": "SKU-OOS",        "name": "Out-of-Stock Widget", "price_cents": 5000, "stock": 0},
        {"sku": "SKU-NO-INV",     "name": "No Inventory Row",  "price_cents": 3000,  "stock": 0},
    ])

    with TestClient(app, headers=default_headers(), raise_server_exceptions=False) as c:
        yield c

    _dbmod.engine = orig_engine
    try:
        _dbmod.set_engine(orig_engine)
    except Exception:
        pass


UID = "test-user-stock-gate"


# ── POST /api/v1/cart/items ───────────────────────────────────────────────────

def test_add_item_in_stock(client_with_stock):
    resp = client_with_stock.post(
        "/api/v1/cart/items",
        json={"uid": UID, "sku": "SKU-INSTOCK-5", "quantity": 2},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert any(it["sku"] == "SKU-INSTOCK-5" for it in body.get("items", []))


def test_add_item_out_of_stock_rejected(client_with_stock):
    resp = client_with_stock.post(
        "/api/v1/cart/items",
        json={"uid": UID, "sku": "SKU-OOS", "quantity": 1},
    )
    assert resp.status_code == 409, resp.text
    detail = resp.json().get("detail", {})
    assert detail.get("error") == "out_of_stock"
    assert detail.get("available") == 0


def test_add_item_no_inventory_row_rejected(client_with_stock):
    """SKU with no inventory row should be treated as OOS (stock=0)."""
    resp = client_with_stock.post(
        "/api/v1/cart/items",
        json={"uid": UID, "sku": "SKU-NO-INV", "quantity": 1},
    )
    assert resp.status_code == 409, resp.text
    assert resp.json().get("detail", {}).get("error") == "out_of_stock"


def test_add_item_quantity_exceeds_stock(client_with_stock):
    """Requesting more than available stock must be rejected."""
    resp = client_with_stock.post(
        "/api/v1/cart/items",
        json={"uid": UID, "sku": "SKU-INSTOCK-5", "quantity": 10},
    )
    assert resp.status_code == 409, resp.text
    detail = resp.json().get("detail", {})
    assert detail.get("error") == "insufficient_stock"
    assert detail.get("available") == 5
    assert detail.get("requested") == 10


def test_add_item_cumulative_cannot_exceed_stock(client_with_stock):
    """Adding items incrementally cannot exceed available stock."""
    # First add: 3 units — OK (stock=5)
    r1 = client_with_stock.post(
        "/api/v1/cart/items",
        json={"uid": UID + "-cum", "sku": "SKU-INSTOCK-5", "quantity": 3},
    )
    assert r1.status_code == 200, r1.text

    # Second add: 3 more — total would be 6, stock is 5 → REJECTED
    r2 = client_with_stock.post(
        "/api/v1/cart/items",
        json={"uid": UID + "-cum", "sku": "SKU-INSTOCK-5", "quantity": 3},
    )
    assert r2.status_code == 409, r2.text
    detail = r2.json().get("detail", {})
    assert detail.get("error") == "insufficient_stock"
    assert detail.get("in_cart") == 3
    assert detail.get("requested") == 3
    assert detail.get("total_would_be") == 6
    assert detail.get("available") == 5


def test_add_last_unit_then_second_rejected(client_with_stock):
    """Add the only unit, then adding one more must be rejected."""
    uid = UID + "-last-unit"
    r1 = client_with_stock.post(
        "/api/v1/cart/items",
        json={"uid": uid, "sku": "SKU-INSTOCK-1", "quantity": 1},
    )
    assert r1.status_code == 200, r1.text

    r2 = client_with_stock.post(
        "/api/v1/cart/items",
        json={"uid": uid, "sku": "SKU-INSTOCK-1", "quantity": 1},
    )
    assert r2.status_code == 409, r2.text
    detail = r2.json().get("detail", {})
    assert detail.get("error") == "insufficient_stock"
    assert detail.get("in_cart") == 1
    assert detail.get("available") == 1


# ── PUT /api/v1/cart/items ────────────────────────────────────────────────────

def test_put_items_within_stock(client_with_stock):
    """PUT with quantities within stock must succeed."""
    resp = client_with_stock.put(
        "/api/v1/cart/items",
        json={"uid": UID + "-put", "items": [
            {"sku": "SKU-INSTOCK-5", "quantity": 3},
        ]},
    )
    assert resp.status_code == 200, resp.text


def test_put_items_exceeds_stock_rejected(client_with_stock):
    """PUT where quantity exceeds available stock must be rejected."""
    resp = client_with_stock.put(
        "/api/v1/cart/items",
        json={"uid": UID + "-put-oos", "items": [
            {"sku": "SKU-INSTOCK-5", "quantity": 10},
        ]},
    )
    assert resp.status_code == 409, resp.text
    detail = resp.json().get("detail", {})
    assert detail.get("error") == "stock_validation_failed"
    assert len(detail.get("insufficient_stock", [])) == 1


def test_put_items_oos_sku_rejected(client_with_stock):
    """PUT with an OOS SKU must be rejected with out_of_stock detail."""
    resp = client_with_stock.put(
        "/api/v1/cart/items",
        json={"uid": UID + "-put-oos2", "items": [
            {"sku": "SKU-OOS", "quantity": 1},
        ]},
    )
    assert resp.status_code == 409, resp.text
    detail = resp.json().get("detail", {})
    assert detail.get("error") == "stock_validation_failed"
    assert any(e.get("sku") == "SKU-OOS" for e in detail.get("out_of_stock", []))


def test_put_items_duplicate_skus_aggregated_and_checked(client_with_stock):
    """PUT with duplicate SKUs: quantities are aggregated before stock check."""
    # SKU-INSTOCK-5 has stock=5. Sending qty=3 + qty=3 = 6 total → REJECTED.
    resp = client_with_stock.put(
        "/api/v1/cart/items",
        json={"uid": UID + "-put-dup", "items": [
            {"sku": "SKU-INSTOCK-5", "quantity": 3},
            {"sku": "SKU-INSTOCK-5", "quantity": 3},
        ]},
    )
    assert resp.status_code == 409, resp.text
    detail = resp.json().get("detail", {})
    assert detail.get("error") == "stock_validation_failed"
    # The aggregated total (6) should be in the insufficient_stock list
    insuf = detail.get("insufficient_stock", [])
    assert len(insuf) == 1
    assert insuf[0].get("sku") == "SKU-INSTOCK-5"
    assert insuf[0].get("requested") == 6
    assert insuf[0].get("available") == 5


def test_put_items_mixed_valid_and_oos_rejected(client_with_stock):
    """PUT with a mix of valid and OOS SKUs must reject the whole payload."""
    resp = client_with_stock.put(
        "/api/v1/cart/items",
        json={"uid": UID + "-put-mix", "items": [
            {"sku": "SKU-INSTOCK-5", "quantity": 2},  # valid
            {"sku": "SKU-OOS",       "quantity": 1},  # OOS → whole request fails
        ]},
    )
    assert resp.status_code == 409, resp.text
    detail = resp.json().get("detail", {})
    assert detail.get("error") == "stock_validation_failed"


# ── POST /api/v1/cart/voucher ─────────────────────────────────────────────────

def test_voucher_endpoint_disabled_by_default(client_with_stock):
    """Voucher endpoint returns 404 unless VOUCHER_ENDPOINT_ENABLED=1."""
    resp = client_with_stock.post(
        "/api/v1/cart/voucher",
        json={"uid": UID, "code": "TEST10"},
    )
    assert resp.status_code == 404, resp.text
    assert "voucher_endpoint_not_enabled" in resp.text
