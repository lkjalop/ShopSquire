"""Operationalize authoritative ATP, allocation parity, supplier recovery, and route proposals.

Revision ID: 20260838_allocation_operationalization
Revises: 20260837_product_identity_alias
"""

from alembic import op
import sqlalchemy as sa


revision = "20260838_allocation_operationalization"
down_revision = "20260837_product_identity_alias"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("supply_allocation_pool", sa.Column("source_id", sa.Text()))
    op.add_column(
        "supply_allocation_pool",
        sa.Column("source_authority", sa.Text(), nullable=False, server_default="unknown"),
    )
    op.add_column(
        "supply_allocation_pool",
        sa.Column("completeness", sa.Text(), nullable=False, server_default="unknown"),
    )
    op.add_column("supply_allocation_pool", sa.Column("source_observation_id", sa.Text()))
    op.add_column("sourcing_batch", sa.Column("fulfillment_case_id", sa.Text()))
    op.add_column("sourcing_batch", sa.Column("draft_content_hash", sa.Text()))
    op.add_column(
        "sourcing_batch",
        sa.Column("updated_at", sa.Text(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_table(
        "allocation_shadow_parity_run",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("case_id", sa.Text()),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("new_allocated_qty", sa.Integer(), nullable=False),
        sa.Column("legacy_reserved_qty", sa.Integer(), nullable=False),
        sa.Column("details_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index(
        "ix_allocation_shadow_parity_scope",
        "allocation_shadow_parity_run",
        ["tenant_id", "case_id", "created_at"],
    )
    op.create_table(
        "supplier_schedule_allocation",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("demand_id", sa.Text(), nullable=False),
        sa.Column("supplier_id", sa.Text(), nullable=False),
        sa.Column("evidence_id", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("eta", sa.Text()),
        sa.Column("observed_at", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.Text()),
        sa.Column("created_at", sa.Text(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["demand_id"], ["demand_commitment.id"]),
        sa.UniqueConstraint("tenant_id", "demand_id", "evidence_id", name="uq_supplier_schedule_evidence"),
        sa.CheckConstraint("quantity >= 0", name="ck_supplier_schedule_quantity"),
        sa.CheckConstraint(
            "status IN ('confirmed','partial','backordered','rejected')",
            name="ck_supplier_schedule_status",
        ),
    )
    op.create_table(
        "buyer_supply_promise",
        sa.Column("tenant_id", sa.Text(), primary_key=True),
        sa.Column("demand_id", sa.Text(), primary_key=True),
        sa.Column("promise_version", sa.Text(), nullable=False),
        sa.Column("promise_state", sa.Text(), nullable=False),
        sa.Column("covered_quantity", sa.Integer(), nullable=False),
        sa.Column("shortfall_quantity", sa.Integer(), nullable=False),
        sa.Column("buyer_message", sa.Text(), nullable=False),
        sa.Column("alternatives_required", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["demand_id"], ["demand_commitment.id"]),
    )
    op.create_table(
        "fulfillment_route_proposal",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("case_id", sa.Text(), nullable=False),
        sa.Column("proposal_version", sa.Text(), nullable=False),
        sa.Column("mode", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("destination_token", sa.Text(), nullable=False),
        sa.Column("eta_min_days", sa.Integer()),
        sa.Column("eta_max_days", sa.Integer()),
        sa.Column("components_json", sa.Text(), nullable=False),
        sa.Column("state_prevented", sa.Text()),
        sa.Column("pii_release_authorized", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.UniqueConstraint("tenant_id", "case_id", "proposal_version", name="uq_route_proposal_version"),
    )


def downgrade() -> None:
    op.drop_table("fulfillment_route_proposal")
    op.drop_table("buyer_supply_promise")
    op.drop_table("supplier_schedule_allocation")
    op.drop_index("ix_allocation_shadow_parity_scope", table_name="allocation_shadow_parity_run")
    op.drop_table("allocation_shadow_parity_run")
    op.drop_column("sourcing_batch", "updated_at")
    op.drop_column("sourcing_batch", "draft_content_hash")
    op.drop_column("sourcing_batch", "fulfillment_case_id")
    op.drop_column("supply_allocation_pool", "source_observation_id")
    op.drop_column("supply_allocation_pool", "completeness")
    op.drop_column("supply_allocation_pool", "source_authority")
    op.drop_column("supply_allocation_pool", "source_id")
