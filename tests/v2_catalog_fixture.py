"""Authoritative V2 catalog fixture for migration-first endpoint tests."""
from __future__ import annotations

import json
from contextlib import contextmanager
from typing import Iterator, Sequence

from sqlalchemy import text

from src.app.models.db import db_session
from src.app.services.taxonomy_registry import (
    add_sold_node,
    ensure_tables,
    upsert_classification,
)


CatalogRow = tuple[str, str, int, int, dict]


@contextmanager
def grounded_v2_catalog(
    rows: Sequence[CatalogRow],
    *,
    node_handle: str,
    source: str,
) -> Iterator[None]:
    """Seed AUD catalog, inventory and approved taxonomy after app DB setup."""
    sold_nodes = tuple(dict.fromkeys(("el-6-6", node_handle)))
    with db_session() as db:
        ensure_tables(db)
        existing_nodes = {
            node: bool(
                db.execute(
                    text(
                        "SELECT 1 FROM sold_taxonomy "
                        "WHERE tenant_id = 'default' AND node_handle = :node"
                    ),
                    {"node": node},
                ).first()
            )
            for node in sold_nodes
        }
        for node in sold_nodes:
            add_sold_node(db, node_handle=node, tenant_id="default")
        for sku, name, price_cents, stock, specs in rows:
            db.execute(
                text(
                    "INSERT OR REPLACE INTO products "
                    "(id, sku, name, price_cents, currency, specs, active) "
                    "VALUES (:sku, :sku, :name, :price, 'AUD', :specs, 1)"
                ),
                {
                    "sku": sku,
                    "name": name,
                    "price": price_cents,
                    "specs": json.dumps(specs),
                },
            )
            db.execute(
                text(
                    "INSERT OR REPLACE INTO inventory "
                    "(id, product_id, stock, warehouse) "
                    "VALUES (:id, :sku, :stock, 'default')"
                ),
                {"id": f"inv-{sku}", "sku": sku, "stock": stock},
            )
            upsert_classification(
                db,
                sku=sku,
                node_handle=node_handle,
                source=source,
                status="approved",
                tenant_id="default",
            )
        db.commit()
    try:
        yield
    finally:
        with db_session() as db:
            for sku, *_ in rows:
                db.execute(
                    text(
                        "DELETE FROM product_classification "
                        "WHERE tenant_id = 'default' AND sku = :sku "
                        "AND source = :source"
                    ),
                    {"sku": sku, "source": source},
                )
                db.execute(
                    text("DELETE FROM inventory WHERE product_id = :sku"),
                    {"sku": sku},
                )
                db.execute(
                    text("DELETE FROM products WHERE id = :sku"),
                    {"sku": sku},
                )
            for node, existed in existing_nodes.items():
                if not existed:
                    db.execute(
                        text(
                            "DELETE FROM sold_taxonomy "
                            "WHERE tenant_id = 'default' AND node_handle = :node"
                        ),
                        {"node": node},
                    )
            db.commit()
