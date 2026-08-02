"""Tenant-scoped demand commitment, supply allocation, and sourcing consolidation ledger.

Revision ID: 20260836_demand_allocation_ledger
Revises: 20260835_security_monitoring_authority
"""

from alembic import op
import sqlalchemy as sa


revision = "20260836_demand_allocation_ledger"
down_revision = "20260835_security_monitoring_authority"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "demand_commitment",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column("case_id", sa.Text()),
        sa.Column("buyer_ref_hash", sa.Text()),
        sa.Column("sku", sa.Text(), nullable=False),
        sa.Column("uom", sa.Text(), nullable=False, server_default="each"),
        sa.Column("destination_id", sa.Text(), nullable=False),
        sa.Column("stage", sa.Text(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("priority_tier", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("required_by", sa.Text()),
        sa.Column("created_at", sa.Text(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.Text(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_demand_commitment_idem"),
        sa.CheckConstraint("stage IN ('provisional','committed','cancelled','fulfilled')", name="ck_demand_stage"),
        sa.CheckConstraint("quantity > 0", name="ck_demand_quantity_positive"),
    )
    op.create_index("ix_demand_commitment_queue", "demand_commitment",
                    ["tenant_id", "sku", "destination_id", "stage", "priority_tier", "created_at"])
    op.create_table(
        "supply_allocation_pool",
        sa.Column("tenant_id", sa.Text(), primary_key=True),
        sa.Column("sku", sa.Text(), primary_key=True),
        sa.Column("uom", sa.Text(), primary_key=True),
        sa.Column("location_id", sa.Text(), primary_key=True),
        sa.Column("atp_quantity", sa.Integer(), nullable=False),
        sa.Column("snapshot_version", sa.Text(), nullable=False),
        sa.Column("observed_at", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.Text()),
        sa.CheckConstraint("atp_quantity >= 0", name="ck_supply_pool_atp_nonnegative"),
    )
    op.create_table(
        "demand_allocation",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("demand_id", sa.Text(), nullable=False),
        sa.Column("sku", sa.Text(), nullable=False),
        sa.Column("uom", sa.Text(), nullable=False),
        sa.Column("location_id", sa.Text(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="allocated"),
        sa.Column("created_at", sa.Text(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("released_at", sa.Text()),
        sa.ForeignKeyConstraint(["demand_id"], ["demand_commitment.id"]),
        sa.UniqueConstraint("tenant_id", "demand_id", "location_id", name="uq_demand_allocation_location"),
        sa.CheckConstraint("quantity > 0", name="ck_demand_allocation_quantity_positive"),
        sa.CheckConstraint("status IN ('allocated','released','consumed')", name="ck_demand_allocation_status"),
    )
    op.create_index("ix_demand_allocation_pool", "demand_allocation",
                    ["tenant_id", "sku", "uom", "location_id", "status"])
    op.create_table(
        "sourcing_batch",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column("consolidation_key", sa.Text(), nullable=False),
        sa.Column("sku", sa.Text(), nullable=False),
        sa.Column("uom", sa.Text(), nullable=False),
        sa.Column("destination_id", sa.Text(), nullable=False),
        sa.Column("supplier_id", sa.Text()),
        sa.Column("status", sa.Text(), nullable=False, server_default="draft"),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("speculative_quantity", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("window_ends_at", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_sourcing_batch_idem"),
        sa.CheckConstraint("quantity > 0", name="ck_sourcing_batch_quantity_positive"),
        sa.CheckConstraint("speculative_quantity >= 0", name="ck_sourcing_batch_speculative_nonnegative"),
    )
    op.create_table(
        "sourcing_batch_demand",
        sa.Column("batch_id", sa.Text(), primary_key=True),
        sa.Column("demand_id", sa.Text(), primary_key=True),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["batch_id"], ["sourcing_batch.id"]),
        sa.ForeignKeyConstraint(["demand_id"], ["demand_commitment.id"]),
        sa.CheckConstraint("quantity > 0", name="ck_sourcing_child_quantity_positive"),
    )


def downgrade() -> None:
    op.drop_table("sourcing_batch_demand")
    op.drop_table("sourcing_batch")
    op.drop_index("ix_demand_allocation_pool", table_name="demand_allocation")
    op.drop_table("demand_allocation")
    op.drop_table("supply_allocation_pool")
    op.drop_index("ix_demand_commitment_queue", table_name="demand_commitment")
    op.drop_table("demand_commitment")
