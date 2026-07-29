"""Seed the full demo catalog through SQLAlchemy on SQLite or PostgreSQL."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from sqlalchemy import text

from scripts.seed_real_catalog import (
    APPLE_PRODUCTS,
    BAGS,
    GAMING_LAPTOPS_REAL,
    HEADSETS,
    LAPTOPS,
    MONITORS,
    NETWORKING,
    STORAGE,
    TABLETS,
    _brand,
    _catalog_identity,
    _image_url,
)
from src.app.models.db import db_session


GROUPS = (
    (LAPTOPS, "Windows Laptops"),
    (GAMING_LAPTOPS_REAL, "Real Gaming Laptops"),
    (APPLE_PRODUCTS, "Apple Products"),
    (MONITORS, "Monitors"),
    (BAGS, "Bags/Cases"),
    (TABLETS, "Tablets"),
    (NETWORKING, "Networking/Routers"),
    (HEADSETS, "Gaming Headsets"),
    (STORAGE, "Storage/Printers"),
)


def _id() -> str:
    return str(uuid.uuid4())


def main() -> None:
    inserted = 0
    grounded = 0
    now = datetime.now(timezone.utc)
    with db_session() as db:
        for products, group_name in GROUPS:
            for product in products:
                category, product_type, node_handle = _catalog_identity(
                    product, group_name,
                )
                sku = str(product["sku"])
                product_id = db.execute(
                    text("SELECT id FROM products WHERE sku=:sku"),
                    {"sku": sku},
                ).scalar()
                if not product_id:
                    product_id = _id()
                    db.execute(
                        text(
                            """
                            INSERT INTO products
                            (id,sku,name,brand,category,product_type,price_cents,
                             currency,specs,active,updated_at,image_url)
                            VALUES
                            (:id,:sku,:name,:brand,:category,:product_type,:price,
                             'AUD',:specs,true,:updated,:image)
                            """
                        ),
                        {
                            "id": product_id,
                            "sku": sku,
                            "name": str(product["name"]),
                            "brand": _brand(product["name"]),
                            "category": category,
                            "product_type": product_type,
                            "price": int(product["price_cents"]),
                            "specs": json.dumps(product.get("specs") or {}),
                            "updated": now,
                            "image": _image_url(sku),
                        },
                    )
                    inserted += 1
                has_inventory = db.execute(
                    text(
                        """
                        SELECT 1 FROM inventory
                        WHERE product_id=:product AND warehouse='default'
                        """
                    ),
                    {"product": product_id},
                ).first()
                if not has_inventory:
                    db.execute(
                        text(
                            """
                            INSERT INTO inventory
                            (id,product_id,stock,warehouse,updated_at)
                            VALUES (:id,:product,24,'default',:updated)
                            """
                        ),
                        {"id": _id(), "product": product_id, "updated": now},
                    )
                classified = db.execute(
                    text(
                        """
                        SELECT 1 FROM product_classification
                        WHERE tenant_id='default' AND sku=:sku
                        """
                    ),
                    {"sku": sku},
                ).first()
                if not classified:
                    db.execute(
                        text(
                            """
                            INSERT INTO product_classification
                            (id,tenant_id,sku,node_handle,taxonomy_release,source,
                             confidence,status,approved_by,updated_at)
                            VALUES
                            (:id,'default',:sku,:node,'2026-05','demo_seed',
                             1.0,'approved','demo_seed',:updated)
                            """
                        ),
                        {
                            "id": _id(), "sku": sku, "node": node_handle,
                            "updated": now,
                        },
                    )
                    grounded += 1
                sold = db.execute(
                    text(
                        """
                        SELECT 1 FROM sold_taxonomy
                        WHERE tenant_id='default' AND node_handle=:node
                        """
                    ),
                    {"node": node_handle},
                ).first()
                if not sold:
                    db.execute(
                        text(
                            """
                            INSERT INTO sold_taxonomy
                            (id,tenant_id,node_handle,taxonomy_release,source,
                             approved_by,updated_at)
                            VALUES
                            (:id,'default',:node,'2026-05','demo_seed',
                             'demo_seed',:updated)
                            """
                        ),
                        {"id": _id(), "node": node_handle, "updated": now},
                    )
        db.commit()
    print(
        f"Portable catalog ready: inserted={inserted} "
        f"classifications_added={grounded}"
    )


if __name__ == "__main__":
    main()
