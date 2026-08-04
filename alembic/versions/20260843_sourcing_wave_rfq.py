"""Persist one governed parent RFQ projection per supplier shipment wave.

Revision ID: 20260843_sourcing_wave_rfq
Revises: 20260842_supplier_governance_authority
"""

from alembic import op
import sqlalchemy as sa


revision = "20260843_sourcing_wave_rfq"
down_revision = "20260842_supplier_governance_authority"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("sourcing_wave") as batch:
        batch.add_column(sa.Column("fulfillment_case_id", sa.Text()))
        batch.add_column(sa.Column("draft_content_hash", sa.Text()))
        batch.add_column(sa.Column("parent_rfq_ref", sa.Text()))
        batch.create_unique_constraint(
            "uq_sourcing_wave_parent_rfq", ["tenant_id", "parent_rfq_ref"]
        )


def downgrade() -> None:
    with op.batch_alter_table("sourcing_wave") as batch:
        batch.drop_constraint("uq_sourcing_wave_parent_rfq", type_="unique")
        batch.drop_column("parent_rfq_ref")
        batch.drop_column("draft_content_hash")
        batch.drop_column("fulfillment_case_id")
