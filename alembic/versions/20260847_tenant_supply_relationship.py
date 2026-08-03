"""Add tenant-approved supply relationships without overloading identity mappings.

Revision ID: 20260847_tenant_supply_relationship
Revises: 20260846_allocation_parity_exception
"""

from alembic import op
import sqlalchemy as sa


revision = "20260847_tenant_supply_relationship"
down_revision = "20260846_allocation_parity_exception"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tenant_supply_relationship",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("relationship_type", sa.Text(), nullable=False),
        sa.Column("subject_id", sa.Text(), nullable=False),
        sa.Column("object_id", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("source_version", sa.Text(), nullable=False),
        sa.Column("observed_at", sa.Text(), nullable=False),
        sa.Column("evidence_ref", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="active"),
        sa.Column("created_at", sa.Text(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint(
            "tenant_id", "relationship_type", "subject_id", "object_id", "source", "source_version",
            name="uq_tenant_supply_relationship_version",
        ),
        sa.CheckConstraint(
            "relationship_type IN ('qualified_substitute_for','transported_via','composed_of')",
            name="ck_tenant_supply_relationship_type",
        ),
        sa.CheckConstraint("status IN ('active','superseded','rejected')", name="ck_tenant_supply_relationship_status"),
        sa.CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_tenant_supply_relationship_confidence"),
    )
    op.create_index(
        "ix_tenant_supply_relationship_resolve", "tenant_supply_relationship",
        ["tenant_id", "relationship_type", "subject_id", "status", "observed_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_tenant_supply_relationship_resolve", table_name="tenant_supply_relationship")
    op.drop_table("tenant_supply_relationship")
