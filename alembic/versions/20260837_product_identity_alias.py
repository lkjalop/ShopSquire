"""Tenant-scoped indexed aliases for canonical sellable product identity."""

from alembic import op

revision = "20260837_product_identity_alias"
down_revision = "20260836_demand_allocation_ledger"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS product_identity_alias (
            tenant_id TEXT NOT NULL,
            normalized_alias TEXT NOT NULL,
            alias_type TEXT NOT NULL,
            sku TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT 'catalog',
            active INTEGER NOT NULL DEFAULT 1,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (tenant_id, normalized_alias, alias_type, sku)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_product_identity_alias_lookup "
        "ON product_identity_alias(tenant_id, normalized_alias, active)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_product_identity_alias_sku "
        "ON product_identity_alias(tenant_id, sku, active)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS product_identity_alias")
