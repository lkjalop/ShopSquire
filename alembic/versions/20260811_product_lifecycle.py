"""Add governed, tenant-scoped product lifecycle transitions.

Revision ID: 20260811_product_lifecycle
Revises: 20260810_account_intelligence
"""
from alembic import op
import sqlalchemy as sa


revision = "20260811_product_lifecycle"
down_revision = "20260810_account_intelligence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "product_lifecycle_state" not in tables:
        op.create_table(
            "product_lifecycle_state",
            sa.Column("id", sa.Text(), primary_key=True),
            sa.Column("tenant_id", sa.Text(), nullable=False),
            sa.Column("sku", sa.Text(), nullable=False),
            sa.Column("state", sa.Text(), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("selling_allowed", sa.Boolean(), nullable=False),
            sa.Column("procurement_allowed", sa.Boolean(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_by", sa.Text(), nullable=False),
            sa.UniqueConstraint(
                "tenant_id", "sku", name="uq_product_lifecycle_tenant_sku"
            ),
        )
    if "product_lifecycle_transition" not in tables:
        op.create_table(
            "product_lifecycle_transition",
            sa.Column("id", sa.Text(), primary_key=True),
            sa.Column("tenant_id", sa.Text(), nullable=False),
            sa.Column("sku", sa.Text(), nullable=False),
            sa.Column("from_state", sa.Text(), nullable=False),
            sa.Column("to_state", sa.Text(), nullable=False),
            sa.Column("reason", sa.Text(), nullable=False),
            sa.Column("evidence_json", sa.Text(), nullable=False),
            sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
            sa.Column("proposed_by", sa.Text(), nullable=False),
            sa.Column("proposed_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("resolved_by", sa.Text()),
            sa.Column("resolved_at", sa.DateTime(timezone=True)),
            sa.Column("expected_version", sa.Integer(), nullable=False),
        )
        op.create_index(
            "ix_product_lifecycle_transition_pending",
            "product_lifecycle_transition",
            ["tenant_id", "status", "proposed_at"],
        )


def downgrade() -> None:
    # Lifecycle decisions are retained as consequential operator evidence.
    return
