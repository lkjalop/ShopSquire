#!/usr/bin/env python3
"""Seed ~35 products into the local SQLite catalog for E2E tests.

Idempotent: updates existing SKUs and creates missing ones.
"""
import random
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.app.models.db import db_session


NUM_PRODUCTS = 35


def make_product(i: int):
    sku = f"P{i:03d}"
    name = f"Acme Widget {i}"
    price_cents = random.choice([1999, 2499, 2999, 3499, 3999, 4999, 5999, 7999, 9999])
    image_url = f"https://via.placeholder.com/300x200/2D3748/FFFFFF?text={name.replace(' ','%20') }"
    specs = {"color": random.choice(["black", "white", "red", "blue"]), "weight_g": random.choice([200, 350, 500]), "warranty_months": random.choice([6,12,24])}
    stock = random.choice([0, 5, 10, 25, 50, 100])
    return dict(sku=sku, name=name, price_cents=price_cents, image_url=image_url, specs=specs, stock=stock)


def seed():
    print(f"Seeding {NUM_PRODUCTS} products...")
    created = 0
    updated = 0
    with db_session() as sess:
        for i in range(1, NUM_PRODUCTS + 1):
            p = make_product(i)
            # upsert product by sku
            row = sess.execute("SELECT id FROM products WHERE sku = :sku", {"sku": p["sku"]}).fetchone()
            if row:
                prod_id = row[0]
                sess.execute(
                    "UPDATE products SET name = :name, price_cents = :price, image_url = :img, specs = :specs, active = 1 WHERE id = :id",
                    {"name": p["name"], "price": p["price_cents"], "img": p["image_url"], "specs": json_dumps(p["specs"]), "id": prod_id},
                )
                updated += 1
            else:
                import uuid
                prod_id = str(uuid.uuid4())
                sess.execute(
                    "INSERT INTO products (id, sku, name, price_cents, currency, image_url, specs, active) VALUES (:id, :sku, :name, :price, 'USD', :img, :specs, 1)",
                    {"id": prod_id, "sku": p["sku"], "name": p["name"], "price": p["price_cents"], "img": p["image_url"], "specs": json_dumps(p["specs"])},
                )
                created += 1

            # upsert inventory row
            inv = sess.execute("SELECT id FROM inventory WHERE product_id = :pid", {"pid": prod_id}).fetchone()
            if inv:
                sess.execute("UPDATE inventory SET stock = :stock WHERE id = :id", {"stock": p["stock"], "id": inv[0]})
            else:
                import uuid
                inv_id = str(uuid.uuid4())
                sess.execute(
                    "INSERT INTO inventory (id, product_id, stock, warehouse) VALUES (:id, :pid, :stock, 'default')",
                    {"id": inv_id, "pid": prod_id, "stock": p["stock"]},
                )
        try:
            sess.commit()
        except Exception:
            sess.rollback()
            raise

    print(f"Seeding complete. created={created} updated={updated}")


def json_dumps(obj):
    import json
    return json.dumps(obj, ensure_ascii=False)


if __name__ == "__main__":
    # Ensure tmp directory exists for sqlite DB
    os.makedirs(os.path.join(os.getcwd(), "tmp"), exist_ok=True)
    seed()
