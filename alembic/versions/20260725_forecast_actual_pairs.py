"""Sealed forecast-versus-actual evidence pairs.

Revision ID: 20260725_forecast_pairs
Revises: 20260725_exec_metrics
"""
from alembic import op
import sqlalchemy as sa


revision = "20260725_forecast_pairs"
down_revision = "20260725_exec_metrics"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "forecast_actual_pair",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(128), nullable=False),
        sa.Column("pair_key", sa.String(192), nullable=False),
        sa.Column("subject_type", sa.String(48), nullable=False),
        sa.Column("subject_id", sa.String(192), nullable=False),
        sa.Column("forecast_value", sa.Numeric(24, 8), nullable=False),
        sa.Column("actual_value", sa.Numeric(24, 8), nullable=False),
        sa.Column("unit", sa.String(48), nullable=False),
        sa.Column("target_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("target_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("forecast_created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actual_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_system", sa.String(96), nullable=False),
        sa.Column("source_records_json", sa.Text(), nullable=False),
        sa.Column("provenance_json", sa.Text(), nullable=False),
        sa.Column("sealed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sealed_by", sa.String(160), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="active"),
        sa.UniqueConstraint("tenant_id", "pair_key", name="uq_forecast_actual_pair"),
    )
    op.create_index(
        "ix_forecast_actual_subject",
        "forecast_actual_pair",
        ["tenant_id", "subject_type", "subject_id", "target_end"],
    )


def downgrade() -> None:
    op.drop_table("forecast_actual_pair")
