"""Durable supplier draft retry queue.

Revision ID: 20260718_fulfillment_draft_retry
Revises: 20260718_hippograph_tenant_scope
"""
from alembic import op
import sqlalchemy as sa

revision = "20260718_fulfillment_draft_retry"
down_revision = "20260718_hippograph_tenant_scope"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "fulfillment_draft_retry",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("case_id", sa.Text(), nullable=False),
        sa.Column("item_ref", sa.Text(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("trace_id", sa.Text()),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_attempt_at", sa.Text(), nullable=False),
        sa.Column("last_error", sa.Text()),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.UniqueConstraint("case_id", "item_ref", "quantity",
                            name="uq_fulfillment_draft_retry_case_item_qty"),
    )
    op.create_index("ix_fulfillment_draft_retry_due", "fulfillment_draft_retry",
                    ["status", "next_attempt_at"])


def downgrade() -> None:
    op.drop_index("ix_fulfillment_draft_retry_due", table_name="fulfillment_draft_retry")
    op.drop_table("fulfillment_draft_retry")
