"""Persist price predictions before later commercial outcomes are known.

Revision ID: 20260873_price_forecasts
Revises: 20260872_commercial_outcomes
"""
from alembic import op
import sqlalchemy as sa


revision = "20260873_price_forecasts"
down_revision = "20260872_commercial_outcomes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "price_forecast_candidates",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("forecast_id", sa.Text(), nullable=False),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("case_id", sa.Text(), nullable=False),
        sa.Column("case_revision", sa.Integer(), nullable=False),
        sa.Column("subject_ref", sa.Text(), nullable=False),
        sa.Column("model_id", sa.Text(), nullable=False),
        sa.Column("model_version", sa.Text(), nullable=False),
        sa.Column("predicted_minor_units", sa.Integer(), nullable=False),
        sa.Column("currency", sa.Text(), nullable=False),
        sa.Column("source_observation_ids_json", sa.JSON(), nullable=False),
        sa.Column("forecast_created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("target_semantics", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("settled_outcome_id", sa.Text(), nullable=True),
        sa.Column("actual_minor_units", sa.Integer(), nullable=True),
        sa.Column("actual_observed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("absolute_error_minor_units", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "forecast_id", name="uq_price_forecast_candidate_tenant"),
    )
    op.create_index(
        "ix_price_forecast_pending_subject",
        "price_forecast_candidates",
        ["tenant_id", "subject_ref", "currency", "status", "forecast_created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_price_forecast_pending_subject", table_name="price_forecast_candidates")
    op.drop_table("price_forecast_candidates")
