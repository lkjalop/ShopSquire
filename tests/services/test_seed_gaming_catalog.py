"""Cold-start gaming-catalog seeding: products + ALIGNED inventory (the out_of_stock fix).

ensure_gaming_catalog must seed GAM-* products AND an inventory row per product, because
batch_stock_levels LEFT JOINs inventory on product_id — a product with no inventory row reads
stock 0 → out_of_stock (which made seeded gaming laptops look unavailable). These tests run against
an isolated temp sqlite so they never touch the shared test DB.
"""
from __future__ import annotations

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from scripts.seed_gaming_laptops import ensure_gaming_catalog, GAMING_LAPTOPS


def _fresh_session(tmp_path):
    eng = create_engine(f"sqlite:///{tmp_path / 'gam.sqlite'}")
    with eng.begin() as c:
        c.execute(text(
            "CREATE TABLE products (id TEXT PRIMARY KEY, sku TEXT UNIQUE, name TEXT, price_cents INTEGER, "
            "currency TEXT, specs TEXT, active INTEGER, updated_at TIMESTAMP, image_url TEXT)"
        ))
        c.execute(text(
            "CREATE TABLE inventory (id TEXT PRIMARY KEY, product_id TEXT, stock INTEGER, "
            "warehouse TEXT, updated_at TIMESTAMP)"
        ))
    return sessionmaker(bind=eng)()


def _stock_by_sku(db):
    # exactly what batch_stock_levels does: LEFT JOIN inventory ON product_id
    rows = db.execute(text(
        "SELECT p.sku, COALESCE(SUM(i.stock), 0) FROM products p "
        "LEFT JOIN inventory i ON i.product_id = p.id WHERE p.sku LIKE 'GAM-%' GROUP BY p.sku"
    )).fetchall()
    return {r[0]: int(r[1]) for r in rows}


def test_seeds_products_and_aligned_inventory(tmp_path):
    db = _fresh_session(tmp_path)
    n = ensure_gaming_catalog(db)
    db.commit()
    assert n == len(GAMING_LAPTOPS) and n >= 5
    # every GAM-* product resolves to stock > 0 (NOT out_of_stock)
    stock = _stock_by_sku(db)
    assert len(stock) == len(GAMING_LAPTOPS)
    assert all(v > 0 for v in stock.values()), f"some GAM-* are out_of_stock: {stock}"


def test_idempotent_no_duplicates_or_double_stock(tmp_path):
    db = _fresh_session(tmp_path)
    ensure_gaming_catalog(db)
    db.commit()
    n2 = ensure_gaming_catalog(db)  # second run inserts nothing
    db.commit()
    assert n2 == 0
    prod_count = db.execute(text("SELECT COUNT(*) FROM products WHERE sku LIKE 'GAM-%'")).scalar()
    inv_count = db.execute(text("SELECT COUNT(*) FROM inventory")).scalar()
    assert prod_count == len(GAMING_LAPTOPS)
    assert inv_count == len(GAMING_LAPTOPS)  # one inventory row per product, not doubled


def test_self_heals_product_missing_inventory(tmp_path):
    # Simulate the OLD bug: a GAM-* product exists with NO inventory row.
    db = _fresh_session(tmp_path)
    db.execute(text(
        "INSERT INTO products (id, sku, name, price_cents, currency, specs, active, updated_at, image_url) "
        "VALUES ('pid-x', :sku, 'x', 100000, 'USD', '{}', 1, NULL, '')"
    ), {"sku": GAMING_LAPTOPS[0]["sku"]})
    db.commit()
    n = ensure_gaming_catalog(db)
    db.commit()
    # the pre-existing product is not re-inserted, but its missing inventory row is added
    assert n == len(GAMING_LAPTOPS) - 1
    healed = db.execute(text("SELECT COUNT(*) FROM inventory WHERE product_id = 'pid-x'")).scalar()
    assert healed == 1
