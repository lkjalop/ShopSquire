"""Separate buyer destination from the merchant location that owns allocatable ATP.

Revision ID: 20260839_demand_fulfillment_location
Revises: 20260838_allocation_operationalization
"""

from alembic import op
import sqlalchemy as sa


revision = "20260839_demand_fulfillment_location"
down_revision = "20260838_allocation_operationalization"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("demand_commitment", sa.Column("fulfillment_location_id", sa.Text()))
    op.create_index(
        "ix_demand_commitment_allocation_queue",
        "demand_commitment",
        ["tenant_id", "sku", "fulfillment_location_id", "stage", "priority_tier", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_demand_commitment_allocation_queue", table_name="demand_commitment")
    op.drop_column("demand_commitment", "fulfillment_location_id")
