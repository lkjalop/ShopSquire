"""Add canonical search-to-demand authority observations.

Revision ID: 20260859_search_demand
Revises: 20260858_return_claims
"""
from alembic import op
import sqlalchemy as sa


revision = "20260859_search_demand"
down_revision = "20260858_return_claims"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "search_demand_observation",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("trace_id", sa.Text(), nullable=False),
        sa.Column("case_id", sa.Text()),
        sa.Column("session_epoch", sa.Text(), nullable=False),
        sa.Column("actor_hash", sa.Text(), nullable=False),
        sa.Column("actor_dedup_class", sa.Text(), nullable=False),
        sa.Column("abuse_status", sa.Text(), nullable=False),
        sa.Column("requirement_fingerprint", sa.Text(), nullable=False),
        sa.Column("query_hash", sa.Text(), nullable=False),
        sa.Column("resolved_sku", sa.Text()),
        sa.Column("unresolved_concept", sa.Text()),
        sa.Column("requested_quantity", sa.Integer()),
        sa.Column("qualification_outcome", sa.Text(), nullable=False),
        sa.Column("evidence_refs_json", sa.Text(), nullable=False),
        sa.Column("source_policy_status", sa.Text(), nullable=False),
        sa.Column("lifecycle_stage", sa.Text(), nullable=False),
        sa.Column("authority", sa.Text(), nullable=False),
        sa.Column("inventory_snapshot_json", sa.Text(), nullable=False),
        sa.Column("observed_at", sa.Text(), nullable=False),
        sa.Column("effective_at", sa.Text(), nullable=False),
        sa.Column("supersedes_id", sa.Text()),
        sa.Column("simulation_only", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["supersedes_id"], ["search_demand_observation.id"],
            name="fk_search_demand_supersedes",
        ),
        sa.CheckConstraint(
            "qualification_outcome IN ('exact','qualified','alternative','no_match','blocked','unresolved')",
            name="ck_search_demand_qualification",
        ),
        sa.CheckConstraint(
            "lifecycle_stage IN ('search_interest','clarification_requested','qualified_interest',"
            "'product_viewed','provisional_cart','buyer_commitment','allocation','order',"
            "'fulfilled','return','cancellation')",
            name="ck_search_demand_stage",
        ),
        sa.CheckConstraint(
            "authority IN ('interest','qualified','provisional','committed','ordered','fulfilled','outcome')",
            name="ck_search_demand_authority",
        ),
    )
    op.create_index(
        "ix_search_demand_tenant_time",
        "search_demand_observation",
        ["tenant_id", "observed_at"],
    )
    op.create_index(
        "ix_search_demand_case_stage",
        "search_demand_observation",
        ["tenant_id", "case_id", "lifecycle_stage"],
    )
    op.create_index(
        "ix_search_demand_requirement",
        "search_demand_observation",
        ["tenant_id", "requirement_fingerprint", "authority"],
    )


def downgrade() -> None:
    op.drop_index("ix_search_demand_requirement", table_name="search_demand_observation")
    op.drop_index("ix_search_demand_case_stage", table_name="search_demand_observation")
    op.drop_index("ix_search_demand_tenant_time", table_name="search_demand_observation")
    op.drop_table("search_demand_observation")
