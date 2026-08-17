"""Persist PII-free realized commercial outcomes.

Revision ID: 20260872_commercial_outcomes
Revises: 20260871_operational_connectors
"""
from alembic import op
import sqlalchemy as sa


revision = "20260872_commercial_outcomes"
down_revision = "20260871_operational_connectors"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "commercial_outcomes",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("outcome_id", sa.Text(), nullable=False),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("order_id", sa.Text(), nullable=False),
        sa.Column("trace_id", sa.Text(), nullable=True),
        sa.Column("outcome_type", sa.Text(), nullable=False),
        sa.Column("amount_cents", sa.Integer(), nullable=True),
        sa.Column("currency", sa.Text(), nullable=True),
        sa.Column("line_items_json", sa.JSON(), nullable=False),
        sa.Column("source_authority", sa.Text(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "outcome_id", name="uq_commercial_outcome_tenant"),
    )
    op.create_index(
        "ix_commercial_outcome_order_time",
        "commercial_outcomes",
        ["tenant_id", "order_id", "observed_at"],
    )
    op.create_index(
        "ix_commercial_outcome_trace_time",
        "commercial_outcomes",
        ["tenant_id", "trace_id", "observed_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_commercial_outcome_trace_time", table_name="commercial_outcomes")
    op.drop_index("ix_commercial_outcome_order_time", table_name="commercial_outcomes")
    op.drop_table("commercial_outcomes")
