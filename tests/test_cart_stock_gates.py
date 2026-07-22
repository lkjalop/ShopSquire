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


def test_cart_currency_comes_from_catalog_product(client_with_stock):
    from src.app.models.db import db_session
    uid = "aud-cart-user"
    with db_session() as db:
        db.execute("UPDATE products SET currency='AUD' WHERE sku='SKU-INSTOCK-5'")
        db.commit()

    response = client_with_stock.post(
        "/api/v1/cart/items",
        json={"uid": uid, "sku": "SKU-INSTOCK-5", "quantity": 2},
    )

    assert response.status_code == 200
    assert response.json()["currency"] == "AUD"
    assert response.json()["items"][0]["currency"] == "AUD"


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


# ── GET /api/v1/cart — cart AGE (Phase 1 TTL labelling) ───────────────────────

def test_cart_age_fresh_when_just_added(client_with_stock):
    """A cart just touched this session reads as FRESH — never nagged as 'previous session'."""
    client_with_stock.post("/api/v1/cart/items", json={"uid": "age-fresh-user", "sku": "SKU-INSTOCK-5", "quantity": 1})
    body = client_with_stock.get("/api/v1/cart", params={"uid": "age-fresh-user"}).json()
    age = body.get("age")
    assert age is not None, body
    assert age["tier"] == "fresh"
    assert age["is_carried"] is False


def test_cart_age_warm_when_carried_over(client_with_stock):
    """Backdate the cart's last-touch 4h → it reads as WARM/carried with a truthful label (the demo case)."""
    from datetime import datetime, timedelta
    from src.app.models.db import db_session

    uid = "age-carried-user"
    client_with_stock.post("/api/v1/cart/items", json={"uid": uid, "sku": "SKU-INSTOCK-5", "quantity": 1})
    ts = (datetime.utcnow() - timedelta(hours=4)).strftime("%Y-%m-%d %H:%M:%S")
    with db_session() as db:
        db.execute("UPDATE draft_orders SET updated_at = :ts WHERE customer_id = :uid", {"ts": ts, "uid": uid})
        db.commit()

    age = client_with_stock.get("/api/v1/cart", params={"uid": uid}).json()["age"]
    assert age["tier"] == "warm"
    assert age["is_carried"] is True
    assert "hour" in age["label"]


# ── per-line added_at (Phase 2: exact "latest" + future per-line TTL) ─────────

def test_added_at_stamped_and_surfaced(client_with_stock):
    """Each cart line carries an added_at timestamp, surfaced on GET so the UI can find the newest line."""
    resp = client_with_stock.post("/api/v1/cart/items", json={"uid": "added-at-user", "sku": "SKU-INSTOCK-5", "quantity": 1})
    line = next(it for it in resp.json()["items"] if it["sku"] == "SKU-INSTOCK-5")
    assert line.get("added_at"), "add_item response line should carry added_at"
    # durable across GET (not just the add echo)
    got = client_with_stock.get("/api/v1/cart", params={"uid": "added-at-user"}).json()
    persisted = next(it for it in got["items"] if it["sku"] == "SKU-INSTOCK-5")
    assert persisted.get("added_at") == line["added_at"]


# ── reload-durable UNDO (Phase 2c: Redis snapshot survives page reload) ───────

class _FakeRedis:
    def __init__(self):
        self.store = {}
    def setex(self, k, ttl, v):
        self.store[k] = v
        return True
    def get(self, k):
        return self.store.get(k)
    def delete(self, k):
        return 1 if self.store.pop(k, None) is not None else 0


def test_cart_undo_roundtrip(client_with_stock):
    """Stash a cleared line -> GET reports undo available -> POST /undo restores it -> snapshot consumed."""
    from src.app.deps import get_redis
    fake = _FakeRedis()
    client_with_stock.app.dependency_overrides[get_redis] = lambda: fake
    try:
        r = client_with_stock.post("/api/v1/cart/undo/stash",
                                   json={"uid": "undo-user", "items": [{"sku": "SKU-INSTOCK-5", "quantity": 2}]})
        assert r.json()["stashed"] is True

        got = client_with_stock.get("/api/v1/cart", params={"uid": "undo-user"}).json()
        assert got["undo"]["available"] is True and got["undo"]["count"] == 1

        u = client_with_stock.post("/api/v1/cart/undo", params={"uid": "undo-user"}).json()
        assert u["restored"] == 1
        assert any(it["sku"] == "SKU-INSTOCK-5" and it["quantity"] == 2 for it in u["items"])

        # snapshot consumed — no second undo
        after = client_with_stock.get("/api/v1/cart", params={"uid": "undo-user"}).json()
        assert after["undo"]["available"] is False
        assert client_with_stock.post("/api/v1/cart/undo", params={"uid": "undo-user"}).status_code == 404
    finally:
        client_with_stock.app.dependency_overrides.pop(get_redis, None)


def test_cart_undo_replaces_current_quantity_instead_of_adding_hidden_demand(client_with_stock):
    from src.app.deps import get_redis
    fake = _FakeRedis()
    client_with_stock.app.dependency_overrides[get_redis] = lambda: fake
    uid = "undo-replace-user"
    try:
        client_with_stock.post("/api/v1/cart/undo/stash",
                               json={"uid": uid, "items": [{"sku": "SKU-INSTOCK-5", "quantity": 4}]})
        added = client_with_stock.post("/api/v1/cart/items",
                                       json={"uid": uid, "sku": "SKU-INSTOCK-5", "quantity": 2})
        assert added.status_code == 200

        restored = client_with_stock.post("/api/v1/cart/undo", params={"uid": uid})

        assert restored.status_code == 200
        line = next(item for item in restored.json()["items"] if item["sku"] == "SKU-INSTOCK-5")
        assert line["quantity"] == 4
    finally:
        client_with_stock.app.dependency_overrides.pop(get_redis, None)


def test_clear_replaces_stale_undo_snapshot_with_the_cart_being_cleared(client_with_stock):
    from src.app.deps import get_redis
    fake = _FakeRedis()
    client_with_stock.app.dependency_overrides[get_redis] = lambda: fake
    uid = "clear-refreshes-undo"
    try:
        client_with_stock.post("/api/v1/cart/undo/stash",
                               json={"uid": uid, "items": [{"sku": "STALE", "quantity": 99}]})
        client_with_stock.post("/api/v1/cart/items",
                               json={"uid": uid, "sku": "SKU-INSTOCK-5", "quantity": 3})

        cleared = client_with_stock.post("/api/v1/cart/clear", params={"uid": uid})
        restored = client_with_stock.post("/api/v1/cart/undo", params={"uid": uid})

        assert cleared.status_code == 200
        assert [(item["sku"], item["quantity"]) for item in restored.json()["items"]] == [
            ("SKU-INSTOCK-5", 3),
        ]
    finally:
        client_with_stock.app.dependency_overrides.pop(get_redis, None)


def test_cart_undo_nothing_to_restore_is_404(client_with_stock):
    from src.app.deps import get_redis
    client_with_stock.app.dependency_overrides[get_redis] = lambda: _FakeRedis()
    try:
        assert client_with_stock.post("/api/v1/cart/undo", params={"uid": "empty-undo"}).status_code == 404
    finally:
        client_with_stock.app.dependency_overrides.pop(get_redis, None)


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


# ── PUT /api/v1/cart/items/{sku} — single-line set (+ procurement-aware over-stock) ──────────────────

def test_set_item_qty_exceeds_stock_rejected_by_default(client_with_stock):
    """The single-line stepper keeps the stock gate: qty > stock without allow_sourcing → 409."""
    resp = client_with_stock.put(
        "/api/v1/cart/items/SKU-INSTOCK-5",
        json={"uid": UID + "-setqty", "sku": "SKU-INSTOCK-5", "quantity": 10},
    )
    assert resp.status_code == 409, resp.text
    detail = resp.json().get("detail", {})
    assert detail.get("error") == "insufficient_stock"
    assert detail.get("available") == 5 and detail.get("requested") == 10


def test_set_item_qty_sourcing_backed_succeeds_with_shortfall(client_with_stock):
    """A multi-intent amendment (allow_sourcing) lets the line exceed stock; the shortfall is reported for
    sourcing at confirm-cart instead of a 409."""
    resp = client_with_stock.put(
        "/api/v1/cart/items/SKU-INSTOCK-5",
        json={"uid": UID + "-setqty-src", "sku": "SKU-INSTOCK-5", "quantity": 10, "allow_sourcing": True},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    line = next((it for it in body.get("items", []) if it["sku"] == "SKU-INSTOCK-5"), None)
    assert line and line["quantity"] == 10                       # cart holds the full requested qty
    assert body.get("sourcing_required") is True
    sf = body.get("sourcing_shortfall") or {}
    assert sf.get("available_now") == 5 and sf.get("shortfall") == 5 and sf.get("requested") == 10


def test_set_item_qty_within_stock_has_no_shortfall(client_with_stock):
    """When the requested qty fits in stock, no sourcing flag/shortfall is attached even with the flag on."""
    resp = client_with_stock.put(
        "/api/v1/cart/items/SKU-INSTOCK-5",
        json={"uid": UID + "-setqty-fit", "sku": "SKU-INSTOCK-5", "quantity": 3, "allow_sourcing": True},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert not body.get("sourcing_required")
    assert body.get("sourcing_shortfall") is None


# ── POST /api/v1/cart/voucher ─────────────────────────────────────────────────

def test_voucher_endpoint_disabled_by_default(client_with_stock):
    """Voucher endpoint returns 404 unless VOUCHER_ENDPOINT_ENABLED=1."""
    resp = client_with_stock.post(
        "/api/v1/cart/voucher",
        json={"uid": UID, "code": "TEST10"},
    )
    assert resp.status_code == 404, resp.text
    assert "voucher_endpoint_not_enabled" in resp.text
