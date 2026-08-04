"""Supplier catalog tables (prod-parity) — suppliers + supplier_products the ranking reads.

inventory_agent._get_best_supplier joins these to rank a SKU's approved suppliers; without them the
default procurement draft path resolves no supplier. Created at runtime via supplier_catalog.ensure_tables;
this is the prod-parity path. Idempotent (CREATE ... IF NOT EXISTS). Chains off the fulfilment head.
trusted_supplier_domains is owned by supplier_domain_guard (runtime); included here IF NOT EXISTS only
for completeness on a fresh DB.
"""
from alembic import op

revision = "20260626_supplier_catalog"
down_revision = "20260626_fulfillment"
branch_labels = None
depends_on = None

TABLE_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS suppliers (
        id TEXT PRIMARY KEY,
        name TEXT,
        unit_cost REAL,
        lead_time_days INTEGER,
        moq INTEGER DEFAULT 0,
        on_time_rate REAL DEFAULT 0,
        reliability_score REAL DEFAULT 0,
        recent_sla_breaches INTEGER DEFAULT 0,
        late_deliveries_30d INTEGER DEFAULT 0,
        active INTEGER DEFAULT 1,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS supplier_products (
        supplier_id TEXT,
        sku TEXT,
        PRIMARY KEY (supplier_id, sku)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS trusted_supplier_domains (
        id TEXT PRIMARY KEY, domain TEXT NOT NULL UNIQUE, supplier_id TEXT, added_by TEXT,
        added_at TEXT DEFAULT CURRENT_TIMESTAMP, active INTEGER DEFAULT 1, notes TEXT
    )
    """,
)
INDEX_STATEMENTS = (
    "CREATE INDEX IF NOT EXISTS ix_supplier_products_sku ON supplier_products(sku)",
    "CREATE INDEX IF NOT EXISTS ix_tsd_supplier ON trusted_supplier_domains(supplier_id)",
)
_DROP_TABLES = ("supplier_products", "suppliers")  # leave trusted_supplier_domains (guard-owned)


def upgrade() -> None:
    for stmt in TABLE_STATEMENTS:
        op.execute(stmt)
    for stmt in INDEX_STATEMENTS:
        op.execute(stmt)


def downgrade() -> None:
    for tbl in _DROP_TABLES:
        op.execute(f"DROP TABLE IF EXISTS {tbl}")
