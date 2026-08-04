"""Add canonical, advisory-only supply disruption observations and projections.

Revision ID: 20260848_disruption_observation
Revises: 20260847_tenant_supply_relationship
"""

from alembic import op
import sqlalchemy as sa


revision = "20260848_disruption_observation"
down_revision = "20260847_tenant_supply_relationship"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "supply_disruption_observation",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("disruption_type", sa.Text(), nullable=False),
        sa.Column("affected_node_ids_json", sa.Text(), nullable=False),
        sa.Column("geography", sa.Text(), nullable=True),
        sa.Column("effective_from", sa.Text(), nullable=False),
        sa.Column("effective_to", sa.Text(), nullable=True),
        sa.Column("observed_at", sa.Text(), nullable=False),
        sa.Column("retrieved_at", sa.Text(), nullable=False),
        sa.Column("published_at", sa.Text(), nullable=True),
        sa.Column("fresh_until", sa.Text(), nullable=False),
        sa.Column("source_id", sa.Text(), nullable=False),
        sa.Column("source_record_id", sa.Text(), nullable=False),
        sa.Column("source_revision", sa.Text(), nullable=False),
        sa.Column("source_licence", sa.Text(), nullable=False),
        sa.Column("evidence_ref", sa.Text(), nullable=False),
        sa.Column("severity", sa.Text(), nullable=False),
        sa.Column("probability_low", sa.Float(), nullable=False),
        sa.Column("probability_high", sa.Float(), nullable=False),
        sa.Column("delay_low_days", sa.Integer(), nullable=False),
        sa.Column("delay_high_days", sa.Integer(), nullable=False),
        sa.Column("cost_low_minor", sa.Integer(), nullable=False),
        sa.Column("cost_high_minor", sa.Integer(), nullable=False),
        sa.Column("currency", sa.Text(), nullable=False),
        sa.Column("contradiction_group", sa.Text(), nullable=True),
        sa.Column("contradiction_status", sa.Text(), nullable=False),
        sa.Column("claim_status", sa.Text(), nullable=False),
        sa.Column("authority", sa.Text(), nullable=False, server_default="advisory_only"),
        sa.Column("recorded_at", sa.Text(), nullable=False),
        sa.Column("recorded_to", sa.Text(), nullable=True),
        sa.Column("supersedes_id", sa.Text(), nullable=True),
        sa.UniqueConstraint(
            "tenant_id", "source_id", "source_record_id", "source_revision",
            name="uq_supply_disruption_source_revision",
        ),
        sa.CheckConstraint(
            "authority = 'advisory_only'", name="ck_supply_disruption_advisory_only"
        ),
        sa.CheckConstraint(
            "probability_low >= 0 AND probability_high <= 1 "
            "AND probability_high >= probability_low",
            name="ck_supply_disruption_probability_range",
        ),
        sa.CheckConstraint(
            "delay_low_days >= 0 AND delay_high_days >= delay_low_days",
            name="ck_supply_disruption_delay_range",
        ),
        sa.CheckConstraint(
            "cost_low_minor >= 0 AND cost_high_minor >= cost_low_minor",
            name="ck_supply_disruption_cost_range",
        ),
    )
    op.create_index(
        "ix_supply_disruption_active",
        "supply_disruption_observation",
        ["tenant_id", "claim_status", "recorded_to", "fresh_until", "effective_from"],
    )
    op.create_table(
        "supply_disruption_impact_projection",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("observation_id", sa.Text(), nullable=False),
        sa.Column("target_node_id", sa.Text(), nullable=False),
        sa.Column("baseline_version", sa.Text(), nullable=False),
        sa.Column("dependency_path_json", sa.Text(), nullable=False),
        sa.Column("projection_json", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("authority", sa.Text(), nullable=False, server_default="proposal_only"),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.UniqueConstraint(
            "tenant_id", "observation_id", "target_node_id", "baseline_version",
            name="uq_supply_disruption_projection_version",
        ),
        sa.CheckConstraint(
            "authority = 'proposal_only'", name="ck_supply_disruption_projection_only"
        ),
    )
    op.create_index(
        "ix_supply_disruption_projection_target",
        "supply_disruption_impact_projection",
        ["tenant_id", "target_node_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_supply_disruption_projection_target",
        table_name="supply_disruption_impact_projection",
    )
    op.drop_table("supply_disruption_impact_projection")
    op.drop_index(
        "ix_supply_disruption_active", table_name="supply_disruption_observation"
    )
    op.drop_table("supply_disruption_observation")
