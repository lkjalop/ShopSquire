"""Persist tenant-owned product, supplier, and facility identity mappings.

Revision ID: 20260844_tenant_supply_mapping
Revises: 20260843_sourcing_wave_rfq
"""

from alembic import op
import sqlalchemy as sa


revision = "20260844_tenant_supply_mapping"
down_revision = "20260843_sourcing_wave_rfq"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tenant_supply_mapping",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("mapping_type", sa.Text(), nullable=False),
        sa.Column("external_id", sa.Text(), nullable=False),
        sa.Column("canonical_id", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("source_version", sa.Text(), nullable=False),
        sa.Column("observed_at", sa.Text(), nullable=False),
        sa.Column("evidence_ref", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="active"),
        sa.Column("created_at", sa.Text(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint(
            "tenant_id", "mapping_type", "external_id", "source", "source_version",
            name="uq_tenant_supply_mapping_version",
        ),
        sa.CheckConstraint(
            "mapping_type IN ('product','supplier','facility')",
            name="ck_tenant_supply_mapping_type",
        ),
        sa.CheckConstraint("status IN ('active','superseded','rejected')", name="ck_tenant_supply_mapping_status"),
        sa.CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_tenant_supply_mapping_confidence"),
    )
    op.create_index(
        "ix_tenant_supply_mapping_resolve",
        "tenant_supply_mapping", ["tenant_id", "mapping_type", "external_id", "status", "observed_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_tenant_supply_mapping_resolve", table_name="tenant_supply_mapping")
    op.drop_table("tenant_supply_mapping")
