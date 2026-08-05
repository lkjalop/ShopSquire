import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from src.app.main import create_app
from src.app.deps import get_redis
from src.app.models.db import db_session
from src.app.services.commerce_catalog import upsert_inventory, upsert_price
from src.app.services.memory import Memory
from src.app.services.recommendation_facade import _read_session_slice
from src.app.services.taxonomy_registry import (
    add_sold_node,
    ensure_tables,
    upsert_classification,
)
from tests.utils import default_headers


_CATALOG = (
    ("MEM-LAP-1", "Gaming Laptop A", 150000, 10),
    ("MEM-LAP-2", "Gaming Laptop B", 180000, 8),
    ("MEM-LAP-3", "Gaming Laptop C", 190000, 6),
    ("MEM-LAP-4", "Gaming Laptop D", 260000, 5),
)


class _MemoryRedis:
    def __init__(self):
        self.values: dict[str, str] = {}
        self.sets: dict[str, set[str]] = {}

    def get(self, key):
        return self.values.get(key)

    def setex(self, key, _ttl, value):
        self.values[key] = value

    def incrby(self, key, amount):
        value = int(self.values.get(key) or 0) + int(amount)
        self.values[key] = str(value)
        return value

    def sadd(self, key, value):
        self.sets.setdefault(key, set()).add(value)

    def srem(self, key, *values):
        self.sets.setdefault(key, set()).difference_update(values)

    def expire(self, _key, _ttl):
        return True

    def delete(self, *keys):
        for key in keys:
            self.values.pop(key, None)


@pytest.fixture(autouse=True)
def _seed_v2_catalog():
    """Use authoritative V2 catalog rows, not the retired retrieval seam."""
    with db_session() as db:
        ensure_tables(db)
        sold_node_existed = bool(
            db.execute(
                text(
                    "SELECT 1 FROM sold_taxonomy "
                    "WHERE tenant_id = 'default' AND node_handle = 'el-6-6'"
                )
            ).first()
        )
        add_sold_node(db, node_handle="el-6-6", tenant_id="default")
        for sku, name, price_cents, stock in _CATALOG:
            db.execute(
                text(
                    "INSERT OR REPLACE INTO products "
                    "(id, sku, name, price_cents, currency, specs, active) "
                    "VALUES (:id, :sku, :name, :price, 'AUD', :specs, 1)"
                ),
                {
                    "id": sku,
                    "sku": sku,
                    "name": name,
                    "price": price_cents,
                    "specs": (
                        '{"ram_gb": 16, "storage_gb": 1024, '
                        '"gaming_style": true, "refresh_hz": 165, '
                        '"gpu": "RTX 4060", "weight_kg": 1.6}'
                    ),
                },
            )
            db.execute(
                text(
                    "INSERT OR REPLACE INTO inventory "
                    "(id, product_id, stock, warehouse) "
                    "VALUES (:id, :product_id, :stock, 'default')"
                ),
                {
                    "id": f"inv-{sku}",
                    "product_id": sku,
                    "stock": stock,
                },
            )
            upsert_classification(
                db,
                sku=sku,
                node_handle="el-6-6",
                source="test_fixture",
                status="approved",
                tenant_id="default",
            )
            # The production feature set reads price and ATP from the canonical
            # commerce boundary. Seeding only the retired products/inventory
            # tables makes this contract depend on a developer's local flags.
            upsert_price(
                db,
                sku=sku,
                list_cents=price_cents,
                source="test_fixture",
                tenant_id="default",
            )
            upsert_inventory(
                db,
                sku=sku,
                on_hand=stock,
                source="test_fixture",
                tenant_id="default",
            )
        db.commit()
    yield
    with db_session() as db:
        for sku, *_ in _CATALOG:
            db.execute(
                text(
                    "DELETE FROM inventory_level "
                    "WHERE tenant_id = 'default' AND sku = :sku "
                    "AND source = 'test_fixture'"
                ),
                {"sku": sku},
            )
            db.execute(
                text(
                    "DELETE FROM price_book_entry "
                    "WHERE tenant_id = 'default' AND sku = :sku "
                    "AND source = 'test_fixture'"
                ),
                {"sku": sku},
            )
            db.execute(
                text(
                    "DELETE FROM product_classification "
                    "WHERE tenant_id = 'default' AND sku = :sku "
                    "AND source = 'test_fixture'"
                ),
                {"sku": sku},
            )
            db.execute(text("DELETE FROM inventory WHERE product_id = :sku"), {"sku": sku})
            db.execute(text("DELETE FROM products WHERE id = :sku"), {"sku": sku})
        if not sold_node_existed:
            db.execute(
                text(
                    "DELETE FROM sold_taxonomy "
                    "WHERE tenant_id = 'default' AND node_handle = 'el-6-6'"
                )
            )
        db.commit()


def test_followup_query_reads_scoped_budget_context():
    redis = _MemoryRedis()
    uid = "followup-memory-user"
    # Postflight write semantics are covered exhaustively in
    # services/test_recommendation_postflight.py. This compatibility contract
    # owns the other half of the boundary: a real tenant/epoch-scoped Memory
    # record must be consumed by a follow-up request. Do not make that assertion
    # conditional on catalog retrieval also succeeding in an unrelated first
    # request.
    Memory(redis, tenant_id="default").set_structured_state(
        uid,
        {
            "last_node_handle": "el-6-6",
            "last_shortlist_skus": [sku for sku, *_ in _CATALOG],
            "constraints": {
                "budget_min_cents": 150_000,
                "budget_max_cents": 190_000,
                "requirements": {},
                "use_cases": ["gaming"],
            },
            "last_lane": "SEARCH",
        },
    )
    session = _read_session_slice(redis, uid, "default")
    constraints = session.get("accepted_constraints") or {}
    assert constraints["budget_max_cents"] == 190_000
    assert constraints["budget_min_cents"] == 150_000
    assert session["prior_node"] == "el-6-6"


def test_followup_widen_budget_by_delta_uses_prior_envelope(monkeypatch):
    # The repository's developer .env may intentionally exercise a one-turn
    # guest quota. This contract owns multi-turn memory semantics, so give the
    # isolated buyer enough bounded allowance to reach the follow-up rather
    # than making the assertion depend on a maintainer's local FinOps profile.
    monkeypatch.setenv("TOKEN_BUDGET_ENABLED", "1")
    monkeypatch.setenv("TOKEN_BUDGET_GUEST_DAILY_TOKENS", "10000")
    app = create_app()
    redis = _MemoryRedis()
    app.dependency_overrides[get_redis] = lambda: redis
    client = TestClient(app, headers=default_headers())
    state: dict[str, dict] = {}

    def _get_context(self, uid: str):
        kv = state.get(uid) or {}
        return {"summary": None, "kv": kv, "recent_retrieval": None}

    def _set_kv(self, uid: str, kv: dict, ttl_seconds=None):
        state[uid] = kv or {}

    monkeypatch.setattr(Memory, "get_context", _get_context)
    monkeypatch.setattr(Memory, "set_kv", _set_kv)

    uid = "followup-memory-user-delta"

    try:
        first = client.get(
            "/api/v1/recommend/suggest",
            params={"uid": uid, "query": "show me gaming laptops between 1500 to 1900"},
        )
        assert first.status_code == 200
        first_constraints = (first.json() or {}).get("constraints_used") or {}
        assert int(first_constraints.get("budget_max")) == 1900
        assert int(first_constraints.get("budget_min")) == 1500

        second = client.get(
            "/api/v1/recommend/suggest",
            params={"uid": uid, "query": "can we widen the budget range by 600?"},
        )
        assert second.status_code == 200, second.text
        second_constraints = (second.json() or {}).get("constraints_used") or {}
        assert int(second_constraints.get("budget_max")) == 2500
        assert int(second_constraints.get("budget_min")) == 2100

        third = client.get(
            "/api/v1/recommend/suggest",
            params={"uid": uid, "query": "only show options with at least 16 GB RAM"},
        )
        assert third.status_code == 200, third.text
        third_body = third.json() or {}
        third_constraints = third_body.get("constraints_used") or {}
        assert third_constraints.get("budget_inherited") is True
        assert int(third_constraints.get("budget_max")) == 2500
        assert int(third_constraints.get("budget_min")) == 2100
        for product in third_body.get("products") or []:
            price_cents = int(product.get("price_cents") or 0)
            assert 210_000 <= price_cents <= 250_000
    finally:
        app.dependency_overrides.pop(get_redis, None)
