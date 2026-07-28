import sqlite3

from scripts.seed_real_catalog import LAPTOPS, seed_group


def test_seed_establishes_inventory_and_taxonomy_grounding(tmp_path):
    db_path = tmp_path / "catalog.sqlite"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE products (
            id TEXT PRIMARY KEY, sku TEXT UNIQUE, name TEXT, brand TEXT,
            category TEXT, product_type TEXT, price_cents INTEGER, currency TEXT,
            specs TEXT, active INTEGER, updated_at TEXT, image_url TEXT
        );
        CREATE TABLE inventory (
            id TEXT PRIMARY KEY, product_id TEXT, stock INTEGER,
            warehouse TEXT, updated_at TEXT
        );
        CREATE TABLE product_classification (
            id TEXT PRIMARY KEY, tenant_id TEXT, sku TEXT, node_handle TEXT,
            taxonomy_release TEXT, source TEXT, confidence REAL, status TEXT,
            approved_by TEXT, updated_at TEXT,
            UNIQUE (tenant_id, sku)
        );
        CREATE TABLE sold_taxonomy (
            id TEXT PRIMARY KEY, tenant_id TEXT, node_handle TEXT,
            taxonomy_release TEXT, source TEXT, approved_by TEXT, updated_at TEXT,
            UNIQUE (tenant_id, node_handle)
        );
        """
    )

    seed_group(conn.cursor(), conn, [LAPTOPS[0]], "Windows Laptops")

    product = conn.execute(
        "SELECT brand, category, product_type FROM products WHERE sku='LAP-0001'"
    ).fetchone()
    assert product == ("Dell", "Laptops", "laptop")
    assert conn.execute("SELECT stock FROM inventory").fetchone()[0] == 24
    assert conn.execute(
        "SELECT node_handle, status FROM product_classification"
    ).fetchone() == ("el-6-6", "approved")
    assert conn.execute("SELECT node_handle FROM sold_taxonomy").fetchone()[0] == "el-6-6"
    conn.close()
