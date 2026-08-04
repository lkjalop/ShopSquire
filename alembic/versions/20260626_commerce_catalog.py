"""Canonical commerce catalog (prod-parity) — price_book_entry + inventory_level.

The two tables the deal-economics JOIN reads and platform adapters (Shopify/Magento/…) write into:
RETAIL price per (sku, channel, currency) and on-hand stock per (sku, location). Created at runtime via
commerce_catalog.ensure_tables; this is the prod-parity path. Idempotent (CREATE ... IF NOT EXISTS).
Chains off the supplier-catalog head. Statements kept identical to the runtime DDL (drift-tested).
"""
from alembic import op

revision = "20260626_commerce_catalog"
down_revision = "20260626_supplier_catalog"
branch_labels = None
depends_on = None

TABLE_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS price_book_entry (
        id TEXT PRIMARY KEY,
        tenant_id TEXT DEFAULT 'default',
        sku TEXT NOT NULL,
        channel TEXT DEFAULT 'default',
        currency TEXT DEFAULT 'AUD',
        list_cents INTEGER,
        sale_cents INTEGER,
        valid_from TEXT,
        valid_to TEXT,
        source TEXT,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS inventory_level (
        id TEXT PRIMARY KEY,
        tenant_id TEXT DEFAULT 'default',
        sku TEXT NOT NULL,
        location_id TEXT DEFAULT 'default',
        on_hand INTEGER DEFAULT 0,
        reserved INTEGER DEFAULT 0,
        available INTEGER,
        source TEXT,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """,
)
INDEX_STATEMENTS = (
    "CREATE UNIQUE INDEX IF NOT EXISTS ix_pbe_key ON price_book_entry(tenant_id, sku, channel, currency)",
    "CREATE UNIQUE INDEX IF NOT EXISTS ix_inv_key ON inventory_level(tenant_id, sku, location_id)",
)
_DROP_TABLES = ("price_book_entry", "inventory_level")


def upgrade() -> None:
    for stmt in TABLE_STATEMENTS:
        op.execute(stmt)
    for stmt in INDEX_STATEMENTS:
        op.execute(stmt)


def downgrade() -> None:
    for tbl in _DROP_TABLES:
        op.execute(f"DROP TABLE IF EXISTS {tbl}")
