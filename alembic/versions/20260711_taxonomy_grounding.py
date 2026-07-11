"""Taxonomy grounding tables (V2 Phase 3.5, GPT-5.6 recommendation #10) — the prod-parity
path for product_classification + sold_taxonomy, which taxonomy_registry.ensure_tables
creates at runtime for sqlite/dev. DDL kept textually identical to
src/app/services/taxonomy_registry.py (drift test enforces it). Idempotent; chains off the
current head.
"""
from alembic import op

revision = "20260711_taxonomy_grounding"
down_revision = "20260627_cart_funnel_event"
branch_labels = None
depends_on = None

TABLE_STATEMENTS = (
    """
CREATE TABLE IF NOT EXISTS product_classification (
    id TEXT PRIMARY KEY,
    tenant_id TEXT DEFAULT 'default',
    sku TEXT NOT NULL,
    node_handle TEXT NOT NULL,
    taxonomy_release TEXT,
    source TEXT,
    confidence REAL,
    status TEXT DEFAULT 'proposed',
    approved_by TEXT,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
)
""",
    """
CREATE TABLE IF NOT EXISTS sold_taxonomy (
    id TEXT PRIMARY KEY,
    tenant_id TEXT DEFAULT 'default',
    node_handle TEXT NOT NULL,
    taxonomy_release TEXT,
    source TEXT,
    approved_by TEXT,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
)
""",
    "CREATE UNIQUE INDEX IF NOT EXISTS ix_pclass_key ON product_classification(tenant_id, sku)",
    "CREATE UNIQUE INDEX IF NOT EXISTS ix_sold_key ON sold_taxonomy(tenant_id, node_handle)",
)


def upgrade() -> None:
    for stmt in TABLE_STATEMENTS:
        op.execute(stmt)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_sold_key")
    op.execute("DROP INDEX IF EXISTS ix_pclass_key")
    op.execute("DROP TABLE IF EXISTS sold_taxonomy")
    op.execute("DROP TABLE IF EXISTS product_classification")
