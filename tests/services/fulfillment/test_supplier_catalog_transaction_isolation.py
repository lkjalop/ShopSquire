from __future__ import annotations

import json

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.app.services.supplier_catalog import seed_demo, supplier_terms


@pytest.fixture
def static_pool_db():
    """A new single-connection in-memory database for every test invocation."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    session = sessionmaker(bind=engine, future=True)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def test_seed_demo_preserves_all_rows_inside_callers_transaction(static_pool_db):
    result = seed_demo(
        static_pool_db,
        skus=["TXN-SKU-A", "TXN-SKU-B"],
        commit=False,
    )

    assert result == {"suppliers": 2, "products": 4, "domains": 2}
    assert static_pool_db.in_transaction()
    assert static_pool_db.execute(text("SELECT count(*) FROM suppliers")).scalar_one() == 2
    assert static_pool_db.execute(text("SELECT count(*) FROM supplier_products")).scalar_one() == 4
    assert static_pool_db.execute(text("SELECT count(*) FROM trusted_supplier_domains")).scalar_one() == 2

    rows = static_pool_db.execute(
        text(
            "SELECT supplier_id, sku, price_breaks "
            "FROM supplier_products ORDER BY supplier_id, sku"
        )
    ).all()
    assert {(row[0], row[1]) for row in rows} == {
        ("SUP-3", "TXN-SKU-A"),
        ("SUP-3", "TXN-SKU-B"),
        ("SUP-7", "TXN-SKU-A"),
        ("SUP-7", "TXN-SKU-B"),
    }
    assert all(json.loads(row[2]) for row in rows)
    assert supplier_terms(static_pool_db, "SUP-7", "TXN-SKU-A")["price_breaks"] == [
        {"min_qty": 25, "discount_pct": 5},
        {"min_qty": 50, "discount_pct": 10},
    ]
    assert supplier_terms(static_pool_db, "SUP-3", "TXN-SKU-B")["price_breaks"] == [
        {"min_qty": 20, "discount_pct": 8},
        {"min_qty": 50, "discount_pct": 15},
    ]


@pytest.mark.parametrize("sku", ["ISOLATED-SKU-A", "ISOLATED-SKU-B"])
def test_seed_demo_is_repeatable_across_isolated_static_pool_fixtures(
    static_pool_db,
    sku,
):
    seed_demo(static_pool_db, skus=[sku], commit=False)

    assert static_pool_db.execute(
        text("SELECT id FROM suppliers ORDER BY id")
    ).scalars().all() == ["SUP-3", "SUP-7"]
    rows = static_pool_db.execute(
        text("SELECT sku, price_breaks FROM supplier_products ORDER BY supplier_id")
    ).all()
    assert [row[0] for row in rows] == [sku, sku]
    assert all(json.loads(row[1]) for row in rows)
