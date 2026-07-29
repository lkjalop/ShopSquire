"""Add immutable grounded supply-hypothesis workflow evidence.

Revision ID: 20260823_supply_hypothesis_workflow
Revises: 20260822_party_redirect_execution
"""

from alembic import op
import sqlalchemy as sa


revision = "20260823_supply_hypothesis_workflow"
down_revision = "20260822_party_redirect_execution"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    if table not in set(inspector.get_table_names()):
        return set()
    return {str(column["name"]) for column in inspector.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "supply_evidence_bundle" not in tables:
        op.create_table(
            "supply_evidence_bundle",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("tenant_id", sa.Text(), nullable=False),
            sa.Column("target_node_id", sa.Text(), nullable=False),
            sa.Column("decision_time", sa.DateTime(timezone=True), nullable=False),
            sa.Column("bundle_hash", sa.String(64), nullable=False),
            sa.Column("bundle_json", sa.Text(), nullable=False),
            sa.Column("created_by", sa.Text(), nullable=False),
            sa.Column(
                "created_at", sa.DateTime(timezone=True), nullable=False,
                server_default=sa.func.now(),
            ),
            sa.UniqueConstraint(
                "tenant_id", "bundle_hash", name="uq_supply_evidence_bundle_hash",
            ),
        )
        op.create_index(
            "ix_supply_evidence_bundle_target",
            "supply_evidence_bundle",
            ["tenant_id", "target_node_id", "decision_time"],
        )
    hypothesis_columns = _columns("causal_impact_hypothesis")
    if "evidence_bundle_id" not in hypothesis_columns:
        op.add_column(
            "causal_impact_hypothesis",
            sa.Column("evidence_bundle_id", sa.String(64)),
        )
    if "supersedes_hypothesis_id" not in hypothesis_columns:
        op.add_column(
            "causal_impact_hypothesis",
            sa.Column("supersedes_hypothesis_id", sa.String(64)),
        )
    if "case_id" not in hypothesis_columns:
        op.add_column(
            "causal_impact_hypothesis", sa.Column("case_id", sa.Text())
        )
    if "created_by" not in hypothesis_columns:
        op.add_column(
            "causal_impact_hypothesis", sa.Column("created_by", sa.Text())
        )
    if "supplier_hypothesis_observation" not in tables:
        op.create_table(
            "supplier_hypothesis_observation",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("tenant_id", sa.Text(), nullable=False),
            sa.Column("hypothesis_id", sa.String(64), nullable=False),
            sa.Column("observation_type", sa.Text(), nullable=False),
            sa.Column("supplier_ref", sa.Text(), nullable=False),
            sa.Column("source_message_id", sa.Text(), nullable=False),
            sa.Column("observation_json", sa.Text(), nullable=False),
            sa.Column("provenance_json", sa.Text(), nullable=False),
            sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("recorded_by", sa.Text(), nullable=False),
            sa.Column(
                "recorded_at", sa.DateTime(timezone=True), nullable=False,
                server_default=sa.func.now(),
            ),
            sa.ForeignKeyConstraint(
                ["hypothesis_id"], ["causal_impact_hypothesis.id"],
            ),
            sa.UniqueConstraint(
                "tenant_id", "source_message_id", "hypothesis_id",
                name="uq_supplier_hypothesis_message",
            ),
        )
        op.create_index(
            "ix_supplier_hypothesis_observation",
            "supplier_hypothesis_observation",
            ["tenant_id", "hypothesis_id", "observed_at"],
        )
    dialect = bind.dialect.name
    immutable_tables = (
        "supply_evidence_bundle",
        "causal_impact_hypothesis",
        "supplier_hypothesis_observation",
        "procurement_option_proposal",
    )
    if dialect == "postgresql":
        op.execute(
            """
            CREATE OR REPLACE FUNCTION reject_supply_workflow_mutation()
            RETURNS trigger AS $$
            BEGIN
              RAISE EXCEPTION 'supply_workflow_records_are_append_only';
            END;
            $$ LANGUAGE plpgsql
            """
        )
        for table in immutable_tables:
            op.execute(
                f"""
                CREATE TRIGGER trg_{table}_no_mutation
                BEFORE UPDATE OR DELETE ON {table}
                FOR EACH ROW EXECUTE FUNCTION reject_supply_workflow_mutation()
                """
            )
    elif dialect == "sqlite":
        for table in immutable_tables:
            op.execute(
                f"""
                CREATE TRIGGER trg_{table}_no_update
                BEFORE UPDATE ON {table}
                BEGIN
                  SELECT RAISE(ABORT, 'supply_workflow_records_are_append_only');
                END
                """
            )
            op.execute(
                f"""
                CREATE TRIGGER trg_{table}_no_delete
                BEFORE DELETE ON {table}
                BEGIN
                  SELECT RAISE(ABORT, 'supply_workflow_records_are_append_only');
                END
                """
            )


def downgrade() -> None:
    # Evidence bundles, supplier observations and hypotheses are retained.
    return
