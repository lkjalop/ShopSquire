"""Add governed causal supply intelligence and synthetic replay records.

Revision ID: 20260817_supply_intelligence
Revises: 20260816_procurement_context
"""
from alembic import op
import sqlalchemy as sa


revision = "20260817_supply_intelligence"
down_revision = "20260816_procurement_context"
branch_labels = None
depends_on = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    tables = _tables()
    if "supply_node" not in tables:
        op.create_table(
            "supply_node",
            sa.Column("id", sa.Text(), primary_key=True),
            sa.Column("tenant_id", sa.Text(), nullable=False),
            sa.Column("node_type", sa.Text(), nullable=False),
            sa.Column("label", sa.Text(), nullable=False),
            sa.Column("attributes_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
            sa.Column("valid_to", sa.DateTime(timezone=True)),
            sa.Column("source_system", sa.Text(), nullable=False),
            sa.Column("source_record_id", sa.Text(), nullable=False),
            sa.Column("provenance_json", sa.Text(), nullable=False),
            sa.Column("evidence_status", sa.Text(), nullable=False),
            sa.Column("simulation_only", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("tenant_id", "source_system", "source_record_id", name="uq_supply_node_source"),
        )
        op.create_index("ix_supply_node_scope", "supply_node", ["tenant_id", "node_type", "valid_to"])
    if "supply_dependency_edge" not in tables:
        op.create_table(
            "supply_dependency_edge",
            sa.Column("id", sa.Text(), primary_key=True),
            sa.Column("tenant_id", sa.Text(), nullable=False),
            sa.Column("from_node_id", sa.Text(), nullable=False),
            sa.Column("to_node_id", sa.Text(), nullable=False),
            sa.Column("relationship_type", sa.Text(), nullable=False),
            sa.Column("properties_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("confidence", sa.Float(), nullable=False),
            sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
            sa.Column("valid_to", sa.DateTime(timezone=True)),
            sa.Column("source_system", sa.Text(), nullable=False),
            sa.Column("source_record_id", sa.Text(), nullable=False),
            sa.Column("provenance_json", sa.Text(), nullable=False),
            sa.Column("evidence_status", sa.Text(), nullable=False),
            sa.Column("simulation_only", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("tenant_id", "source_system", "source_record_id", name="uq_supply_edge_source"),
        )
        op.create_index("ix_supply_edge_from", "supply_dependency_edge", ["tenant_id", "from_node_id", "valid_to"])
        op.create_index("ix_supply_edge_to", "supply_dependency_edge", ["tenant_id", "to_node_id", "valid_to"])
    if "supply_signal_observation" not in tables:
        op.create_table(
            "supply_signal_observation",
            sa.Column("id", sa.Text(), primary_key=True),
            sa.Column("tenant_id", sa.Text(), nullable=False),
            sa.Column("subject_node_id", sa.Text(), nullable=False),
            sa.Column("signal_type", sa.Text(), nullable=False),
            sa.Column("direction", sa.Text(), nullable=False),
            sa.Column("magnitude_json", sa.Text(), nullable=False),
            sa.Column("measurement_json", sa.Text(), nullable=False),
            sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
            sa.Column("effective_to", sa.DateTime(timezone=True)),
            sa.Column("published_at", sa.DateTime(timezone=True)),
            sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("source_system", sa.Text(), nullable=False),
            sa.Column("source_record_id", sa.Text(), nullable=False),
            sa.Column("source_policy_json", sa.Text(), nullable=False),
            sa.Column("provenance_json", sa.Text(), nullable=False),
            sa.Column("confidence", sa.Float(), nullable=False),
            sa.Column("status", sa.Text(), nullable=False),
            sa.Column("simulation_only", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("tenant_id", "source_system", "source_record_id", name="uq_supply_signal_source"),
        )
        op.create_index("ix_supply_signal_scope", "supply_signal_observation", ["tenant_id", "subject_node_id", "available_at"])
    if "causal_impact_hypothesis" not in tables:
        op.create_table(
            "causal_impact_hypothesis",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("tenant_id", sa.Text(), nullable=False),
            sa.Column("target_node_id", sa.Text(), nullable=False),
            sa.Column("decision_time", sa.DateTime(timezone=True), nullable=False),
            sa.Column("hypothesis_json", sa.Text(), nullable=False),
            sa.Column("status", sa.Text(), nullable=False),
            sa.Column("authority", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
        op.create_index("ix_supply_hypothesis_target", "causal_impact_hypothesis", ["tenant_id", "target_node_id", "decision_time"])
    if "procurement_option_proposal" not in tables:
        op.create_table(
            "procurement_option_proposal",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("tenant_id", sa.Text(), nullable=False),
            sa.Column("hypothesis_id", sa.String(64), nullable=False),
            sa.Column("case_id", sa.Text()),
            sa.Column("options_json", sa.Text(), nullable=False),
            sa.Column("status", sa.Text(), nullable=False),
            sa.Column("authority", sa.Text(), nullable=False),
            sa.Column("created_by", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
    if "synthetic_supply_scenario_manifest" not in tables:
        op.create_table(
            "synthetic_supply_scenario_manifest",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("tenant_id", sa.Text(), nullable=False),
            sa.Column("scenario_id", sa.Text(), nullable=False),
            sa.Column("generator_version", sa.Text(), nullable=False),
            sa.Column("seed", sa.Integer(), nullable=False),
            sa.Column("parameter_hash", sa.String(64), nullable=False),
            sa.Column("manifest_json", sa.Text(), nullable=False),
            sa.Column("authority", sa.Text(), nullable=False, server_default="simulation_only"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("tenant_id", "scenario_id", "generator_version", "seed", name="uq_synthetic_supply_replay"),
        )


def downgrade() -> None:
    # Supply evidence and replay manifests are retained for audit/reproducibility.
    return
