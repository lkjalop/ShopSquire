"""Canonical catalog identity + integration seam (prod-parity) — product + variant + external_ref.

Completes the canonical model alongside commerce_catalog (price/stock): catalog identity (product),
the sellable SKU (variant), and the platform↔canonical mapping (external_ref) that lets a second
ecommerce platform integrate without touching core. Created at runtime via catalog_entities.ensure_tables;
this is the prod-parity path. Idempotent. Chains off the commerce-catalog head. Drift-tested.
"""
from alembic import op

revision = "20260626_catalog_entities"
down_revision = "20260626_commerce_catalog"
branch_labels = None
depends_on = None

TABLE_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS product (
        id TEXT PRIMARY KEY,
        tenant_id TEXT DEFAULT 'default',
        title TEXT,
        brand TEXT,
        category TEXT,
        gtin TEXT,
        attributes_json TEXT,
        status TEXT DEFAULT 'active',
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS variant (
        id TEXT PRIMARY KEY,
        tenant_id TEXT DEFAULT 'default',
        product_id TEXT,
        sku TEXT,
        gtin TEXT,
        attributes_json TEXT,
        status TEXT DEFAULT 'active',
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS external_ref (
        id TEXT PRIMARY KEY,
        tenant_id TEXT DEFAULT 'default',
        entity_type TEXT,
        entity_id TEXT,
        platform TEXT,
        external_id TEXT,
        raw_json TEXT,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """,
)
INDEX_STATEMENTS = (
    "CREATE UNIQUE INDEX IF NOT EXISTS ix_variant_sku ON variant(tenant_id, sku)",
    "CREATE INDEX IF NOT EXISTS ix_variant_product ON variant(product_id)",
    "CREATE UNIQUE INDEX IF NOT EXISTS ix_extref_key ON external_ref(tenant_id, platform, entity_type, external_id)",
)
_DROP_TABLES = ("external_ref", "variant", "product")


def upgrade() -> None:
    for stmt in TABLE_STATEMENTS:
        op.execute(stmt)
    for stmt in INDEX_STATEMENTS:
        op.execute(stmt)


def downgrade() -> None:
    for tbl in _DROP_TABLES:
        op.execute(f"DROP TABLE IF EXISTS {tbl}")
