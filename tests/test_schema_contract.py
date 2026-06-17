"""Schema-contract test: columns the code SELECTs from `products` must exist.

This single test would have caught all three schema-mismatch bugs found in 2026-06:
the upsell `brand` column (fixed), and the still-open `p.category`/`p.brand` refs in
candidate_retriever.py + upsell_engine.py that make those legs silently return nothing.

It introspects the live products schema and asserts (a) the required base columns
exist, and (b) flags the columns the code references but the schema lacks. The (b)
group is xfail until schema hardening (Thread 2 / step 5) lands the columns, at which
point this turns green and the xfail markers are removed.
"""
from __future__ import annotations

import pytest
from sqlalchemy import text

from src.app.models.db import db_session


def _products_columns() -> set[str]:
    with db_session() as db:
        rows = db.execute(text("PRAGMA table_info(products)")).fetchall()
    return {str(r[1]) for r in rows}


def test_products_has_required_base_columns():
    cols = _products_columns()
    required = {"id", "sku", "name", "price_cents", "currency", "specs", "active"}
    missing = required - cols
    assert not missing, f"products schema missing base columns: {missing}"


@pytest.mark.xfail(reason="schema hardening pending (Thread 2 / step 5): brand/category/"
                          "product_type are referenced by candidate_retriever.py + "
                          "upsell_engine.py but not in the products schema", strict=False)
def test_products_has_columns_referenced_by_code():
    cols = _products_columns()
    # Columns the codebase SELECTs from products (grep: p.brand / p.category / product_type).
    referenced = {"brand", "category", "product_type"}
    missing = referenced - cols
    assert not missing, f"code references products columns that do not exist: {missing}"
