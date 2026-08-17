"""Append-only shopping-case operational observations.

Revision ID: 20260870_case_operational_observations
Revises: 20260869_case_interpretation_audit
"""
from alembic import op
import sqlalchemy as sa


revision = "20260870_case_operational_observations"
down_revision = "20260869_case_interpretation_audit"
branch_labels = None
depends_on = None


def upgrade() -> None:
    table = "shopping_case_operational_observations"
    inspector = sa.inspect(op.get_bind())
    # The portfolio SQLite profile historically ran metadata.create_all before
    # Alembic. Adopt that structurally compatible table instead of leaving the
    # non-transactional migration permanently unretryable.
    if table not in inspector.get_table_names():
        op.create_table(
            table,
            sa.Column("id", sa.Text(), primary_key=True),
            sa.Column("observation_id", sa.Text(), nullable=False),
            sa.Column("tenant_id", sa.Text(), nullable=False),
            sa.Column("case_id", sa.Text(), nullable=False),
            sa.Column("case_revision", sa.Integer(), nullable=False),
            sa.Column("kind", sa.Text(), nullable=False),
            sa.Column("subject_ref", sa.Text(), nullable=False),
            sa.Column("location_ref", sa.Text(), nullable=True),
            sa.Column("value_json", sa.JSON(), nullable=False),
            sa.Column("source_type", sa.Text(), nullable=False),
            sa.Column("evidence_ref", sa.Text(), nullable=False),
            sa.Column("known_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("decision_run_id", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint(
                "tenant_id", "observation_id",
                name="uq_case_operational_observation_tenant",
            ),
        )
        inspector = sa.inspect(op.get_bind())
    indexes = {row["name"] for row in inspector.get_indexes(table)}
    index = "ix_case_operational_observation_case_revision"
    if index not in indexes:
        op.create_index(index, table, ["tenant_id", "case_id", "case_revision"])


def downgrade() -> None:
    op.drop_index(
        "ix_case_operational_observation_case_revision",
        table_name="shopping_case_operational_observations",
    )
    op.drop_table("shopping_case_operational_observations")
