"""Persist governed operational connector enrollment and run truth.

Revision ID: 20260871_operational_connectors
Revises: 20260870_case_operational_observations
"""
from alembic import op
import sqlalchemy as sa


revision = "20260871_operational_connectors"
down_revision = "20260870_case_operational_observations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "operational_connector_enrollments",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("connector_id", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("capability", sa.Text(), nullable=False),
        sa.Column("endpoint_origin", sa.Text(), nullable=False),
        sa.Column("auth_mode", sa.Text(), nullable=False),
        sa.Column("credential_ref", sa.Text(), nullable=True),
        sa.Column("allowed_schema_versions_json", sa.JSON(), nullable=False),
        sa.Column("freshness_sla_seconds", sa.Integer(), nullable=False),
        sa.Column("execution_mode", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("reviewed_by", sa.Text(), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "connector_id", name="uq_operational_connector_tenant"),
    )
    op.create_table(
        "operational_connector_runs",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("run_id", sa.Text(), nullable=False),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("connector_id", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("execution_mode", sa.Text(), nullable=False),
        sa.Column("source_schema_version", sa.Text(), nullable=True),
        sa.Column("delivery_id", sa.Text(), nullable=True),
        sa.Column("watermark_after", sa.Text(), nullable=True),
        sa.Column("normalized_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rejected_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("external_calls", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("paid_calls", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "run_id", name="uq_operational_connector_run_tenant"),
    )
    op.create_index(
        "ix_operational_connector_run_latest",
        "operational_connector_runs",
        ["tenant_id", "connector_id", "completed_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_operational_connector_run_latest", table_name="operational_connector_runs")
    op.drop_table("operational_connector_runs")
    op.drop_table("operational_connector_enrollments")
