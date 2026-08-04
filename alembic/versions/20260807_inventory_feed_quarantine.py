"""Add separate custody for quarantined inventory feed observations.

Revision ID: 20260807_inventory_quarantine
Revises: 20260806_supplier_active
"""
from alembic import op
import sqlalchemy as sa


revision = "20260807_inventory_quarantine"
down_revision = "20260806_supplier_active"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("supplier_feed_quarantine"):
        op.create_table(
            "supplier_feed_quarantine",
            sa.Column("id", sa.Text(), primary_key=True),
            sa.Column("tenant_id", sa.Text(), nullable=False),
            sa.Column("source", sa.Text(), nullable=False),
            sa.Column("sku", sa.Text(), nullable=False),
            sa.Column("warehouse", sa.Text(), nullable=True),
            sa.Column("stock", sa.Integer(), nullable=True),
            sa.Column("risk_score", sa.Float(), nullable=False),
            sa.Column("reasons_json", sa.Text(), nullable=False),
            sa.Column("raw_json", sa.Text(), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
        )
    indexes = {
        item["name"]
        for item in sa.inspect(bind).get_indexes("supplier_feed_quarantine")
    }
    if "ix_supplier_feed_quarantine_tenant_created" not in indexes:
        op.create_index(
            "ix_supplier_feed_quarantine_tenant_created",
            "supplier_feed_quarantine",
            ["tenant_id", "created_at"],
        )
    if "ix_supplier_feed_quarantine_tenant_source_sku" not in indexes:
        op.create_index(
            "ix_supplier_feed_quarantine_tenant_source_sku",
            "supplier_feed_quarantine",
            ["tenant_id", "source", "sku"],
        )


def downgrade() -> None:
    # Quarantine evidence is operationally material and may be under retention.
    return
