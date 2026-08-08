"""Persist revision-bound same-case fulfilment continuation.

Revision ID: 20260861_case_fulfillment
Revises: 20260860_product_evidence
"""
from alembic import op
import sqlalchemy as sa


revision = "20260861_case_fulfillment"
down_revision = "20260860_product_evidence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "shopping_case_fulfillment_selections",
        sa.Column("selection_id", sa.Text(), primary_key=True),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("case_id", sa.Text(), nullable=False),
        sa.Column("uid", sa.Text(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("choice", sa.Text(), nullable=False),
        sa.Column("preferred_sku", sa.Text(), nullable=False),
        sa.Column("requested_quantity", sa.Integer(), nullable=False),
        sa.Column("available_now", sa.Integer(), nullable=False),
        sa.Column("offers_json", sa.JSON(), nullable=False),
        sa.Column("selection_idempotency_key", sa.Text(), nullable=False),
        sa.Column("selected_offer_id", sa.Text(), nullable=True),
        sa.Column("confirmation_idempotency_key", sa.Text(), nullable=True),
        sa.Column("cart_plan_id", sa.Text(), nullable=True),
        sa.Column("cart_result_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "tenant_id", "case_id", "revision", name="uq_case_fulfillment_revision",
        ),
        sa.UniqueConstraint(
            "tenant_id", "case_id", "selection_idempotency_key",
            name="uq_case_fulfillment_selection_idempotency",
        ),
    )
    op.create_index(
        "ix_case_fulfillment_owner",
        "shopping_case_fulfillment_selections",
        ["tenant_id", "case_id", "uid", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_case_fulfillment_owner", table_name="shopping_case_fulfillment_selections")
    op.drop_table("shopping_case_fulfillment_selections")
