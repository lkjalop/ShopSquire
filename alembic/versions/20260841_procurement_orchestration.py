"""Add supplier sourcing waves, direct-ship privacy grants, and temporal dependencies.

Revision ID: 20260841_procurement_orchestration
Revises: 20260840_security_threshold_authority
"""

from alembic import op
import sqlalchemy as sa


revision = "20260841_procurement_orchestration"
down_revision = "20260840_security_threshold_authority"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sourcing_wave",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column("supplier_id", sa.Text(), nullable=False),
        sa.Column("supplier_facility_id", sa.Text(), nullable=False),
        sa.Column("currency", sa.Text(), nullable=False),
        sa.Column("incoterm", sa.Text(), nullable=False),
        sa.Column("merchant_destination_id", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="draft"),
        sa.Column("window_ends_at", sa.Text(), nullable=False),
        sa.Column("standalone_freight_cents", sa.Integer(), nullable=False),
        sa.Column("consolidated_freight_cents", sa.Integer(), nullable=False),
        sa.Column("handling_cents", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("estimated_savings_cents", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.Text(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_sourcing_wave_idem"),
        sa.CheckConstraint("status IN ('draft','rfq_drafted','approved','closed','cancelled')", name="ck_sourcing_wave_status"),
        sa.CheckConstraint("standalone_freight_cents >= 0", name="ck_wave_standalone_freight"),
        sa.CheckConstraint("consolidated_freight_cents >= 0", name="ck_wave_consolidated_freight"),
        sa.CheckConstraint("handling_cents >= 0", name="ck_wave_handling"),
    )
    op.create_index(
        "ix_sourcing_wave_scope", "sourcing_wave",
        ["tenant_id", "supplier_id", "supplier_facility_id", "status", "window_ends_at"],
    )
    op.create_table(
        "sourcing_wave_batch",
        sa.Column("wave_id", sa.Text(), primary_key=True),
        sa.Column("batch_id", sa.Text(), primary_key=True),
        sa.ForeignKeyConstraint(["wave_id"], ["sourcing_wave.id"]),
        sa.ForeignKeyConstraint(["batch_id"], ["sourcing_batch.id"]),
        sa.UniqueConstraint("batch_id", name="uq_sourcing_batch_one_wave"),
    )
    op.create_table(
        "direct_ship_authorization",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("case_id", sa.Text(), nullable=False),
        sa.Column("supplier_id", sa.Text(), nullable=False),
        sa.Column("destination_token", sa.Text(), nullable=False),
        sa.Column("jurisdiction", sa.Text(), nullable=False),
        sa.Column("purpose", sa.Text(), nullable=False),
        sa.Column("permitted_fields_json", sa.Text(), nullable=False),
        sa.Column("retention_until", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("authorized_by", sa.Text(), nullable=False),
        sa.Column("authorized_at", sa.Text(), nullable=False),
        sa.Column("withdrawn_at", sa.Text()),
        sa.Column("audit_evidence_id", sa.Text(), nullable=False),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_direct_ship_auth_idem"),
        sa.CheckConstraint("status IN ('active','withdrawn','expired')", name="ck_direct_ship_auth_status"),
    )
    op.create_index(
        "ix_direct_ship_auth_case", "direct_ship_authorization",
        ["tenant_id", "case_id", "supplier_id", "status"],
    )
    op.create_table(
        "temporal_dependency",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("source_type", sa.Text(), nullable=False),
        sa.Column("source_id", sa.Text(), nullable=False),
        sa.Column("source_version", sa.Text(), nullable=False),
        sa.Column("derived_type", sa.Text(), nullable=False),
        sa.Column("derived_id", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="active"),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("invalidated_at", sa.Text()),
        sa.Column("invalidation_reason", sa.Text()),
        sa.UniqueConstraint(
            "tenant_id", "source_type", "source_id", "source_version", "derived_type", "derived_id",
            name="uq_temporal_dependency",
        ),
        sa.CheckConstraint("status IN ('active','invalidated')", name="ck_temporal_dependency_status"),
    )
    op.create_index(
        "ix_temporal_dependency_source", "temporal_dependency",
        ["tenant_id", "source_type", "source_id", "source_version", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_temporal_dependency_source", table_name="temporal_dependency")
    op.drop_table("temporal_dependency")
    op.drop_index("ix_direct_ship_auth_case", table_name="direct_ship_authorization")
    op.drop_table("direct_ship_authorization")
    op.drop_table("sourcing_wave_batch")
    op.drop_index("ix_sourcing_wave_scope", table_name="sourcing_wave")
    op.drop_table("sourcing_wave")

