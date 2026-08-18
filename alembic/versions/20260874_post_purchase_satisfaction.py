"""Persist affirmative post-purchase satisfaction observations.

Revision ID: 20260874_post_purchase_satisfaction
Revises: 20260873_price_forecasts
"""
from alembic import op
import sqlalchemy as sa


revision = "20260874_post_purchase_satisfaction"
down_revision = "20260873_price_forecasts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "post_purchase_satisfaction",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("submission_id", sa.Text(), nullable=False),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("order_id", sa.Text(), nullable=False),
        sa.Column("trace_id", sa.Text(), nullable=True),
        sa.Column("rating", sa.Integer(), nullable=False),
        sa.Column("fulfilled_as_expected", sa.Boolean(), nullable=False),
        sa.Column("would_recommend", sa.Boolean(), nullable=True),
        sa.Column("reason_codes_json", sa.JSON(), nullable=False),
        sa.Column("actor_class", sa.Text(), nullable=False),
        sa.Column("source_authority", sa.Text(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "submission_id", name="uq_satisfaction_submission_tenant"),
        sa.CheckConstraint("rating >= 1 AND rating <= 5", name="ck_satisfaction_rating_range"),
    )
    op.create_index(
        "ix_post_purchase_satisfaction_order",
        "post_purchase_satisfaction",
        ["tenant_id", "order_id", "observed_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_post_purchase_satisfaction_order", table_name="post_purchase_satisfaction")
    op.drop_table("post_purchase_satisfaction")
