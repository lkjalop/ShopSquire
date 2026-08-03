"""Persist tenant supplier sourcing policies and queue observations.

Revision ID: 20260845_supplier_sourcing_authority
Revises: 20260844_tenant_supply_mapping
"""

from alembic import op
import sqlalchemy as sa


revision = "20260845_supplier_sourcing_authority"
down_revision = "20260844_tenant_supply_mapping"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "supplier_sourcing_policy",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("supplier_id", sa.Text(), nullable=False),
        sa.Column("supplier_facility_id", sa.Text(), nullable=False),
        sa.Column("policy_version", sa.Text(), nullable=False),
        sa.Column("max_open_requests", sa.Integer(), nullable=False),
        sa.Column("max_open_units", sa.Integer(), nullable=False),
        sa.Column("max_request_units", sa.Integer(), nullable=False),
        sa.Column("max_dispatches_per_hour", sa.Integer(), nullable=False),
        sa.Column("acknowledgement_sla_seconds", sa.Integer(), nullable=False),
        sa.Column("effective_from", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="active"),
        sa.Column("created_at", sa.Text(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint(
            "tenant_id", "supplier_id", "supplier_facility_id", "policy_version",
            name="uq_supplier_sourcing_policy_version",
        ),
        sa.CheckConstraint(
            "max_open_requests > 0 AND max_open_units > 0 AND max_request_units > 0 "
            "AND max_dispatches_per_hour > 0 AND acknowledgement_sla_seconds > 0",
            name="ck_supplier_sourcing_policy_positive",
        ),
        sa.CheckConstraint("status IN ('active','superseded')", name="ck_supplier_sourcing_policy_status"),
    )
    op.create_index(
        "ix_supplier_sourcing_policy_active", "supplier_sourcing_policy",
        ["tenant_id", "supplier_id", "supplier_facility_id", "status", "effective_from"],
    )
    op.create_table(
        "supplier_sourcing_queue_observation",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("supplier_id", sa.Text(), nullable=False),
        sa.Column("supplier_facility_id", sa.Text(), nullable=False),
        sa.Column("source_id", sa.Text(), nullable=False),
        sa.Column("source_version", sa.Text(), nullable=False),
        sa.Column("observed_at", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.Text(), nullable=False),
        sa.Column("open_requests", sa.Integer(), nullable=False),
        sa.Column("open_units", sa.Integer(), nullable=False),
        sa.Column("dispatches_last_hour", sa.Integer(), nullable=False),
        sa.Column("oldest_unacknowledged_at", sa.Text()),
        sa.Column("created_at", sa.Text(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint(
            "tenant_id", "supplier_id", "supplier_facility_id", "source_id", "source_version",
            name="uq_supplier_sourcing_queue_version",
        ),
        sa.CheckConstraint(
            "open_requests >= 0 AND open_units >= 0 AND dispatches_last_hour >= 0",
            name="ck_supplier_sourcing_queue_nonnegative",
        ),
    )
    op.create_index(
        "ix_supplier_sourcing_queue_latest", "supplier_sourcing_queue_observation",
        ["tenant_id", "supplier_id", "supplier_facility_id", "observed_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_supplier_sourcing_queue_latest", table_name="supplier_sourcing_queue_observation")
    op.drop_table("supplier_sourcing_queue_observation")
    op.drop_index("ix_supplier_sourcing_policy_active", table_name="supplier_sourcing_policy")
    op.drop_table("supplier_sourcing_policy")
