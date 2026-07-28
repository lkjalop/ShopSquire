"""Add recoverable execution claims to inventory reorder proposals.

Revision ID: 20260804_inventory_claims
Revises: 20260803_outbound_jobs
"""
from alembic import op
import sqlalchemy as sa


revision = "20260804_inventory_claims"
down_revision = "20260803_outbound_jobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {
        item["name"]
        for item in sa.inspect(op.get_bind()).get_columns("inventory_reorder_proposal")
    }
    if "execution_started_at" not in columns:
        op.add_column(
            "inventory_reorder_proposal",
            sa.Column("execution_started_at", sa.DateTime(timezone=True)),
        )


def downgrade() -> None:
    columns = {
        item["name"]
        for item in sa.inspect(op.get_bind()).get_columns("inventory_reorder_proposal")
    }
    if "execution_started_at" in columns:
        op.drop_column("inventory_reorder_proposal", "execution_started_at")
