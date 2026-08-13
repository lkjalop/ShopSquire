"""Persist typed Hippograph journey evidence.

Revision ID: 20260863_hippograph_edges
Revises: 20260862_case_publishers
"""
from alembic import op
import sqlalchemy as sa


revision = "20260863_hippograph_edges"
down_revision = "20260862_case_publishers"
branch_labels = None
depends_on = None


_EXPECTED_COLUMNS = {
    "id", "edge_id", "tenant_id", "case_id", "source_id", "source_kind",
    "target_id", "target_kind", "relation", "signal_class", "evidence_id",
    "source_authority", "confidence_micros", "observed_at", "effective_at",
    "valid_to", "supersedes_edge_id", "contradicts_edge_ids_json",
    "attributes_json", "created_at",
}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "hippograph_journey_edges" not in inspector.get_table_names():
        op.create_table(
            "hippograph_journey_edges",
            sa.Column("id", sa.Text(), primary_key=True),
            sa.Column("edge_id", sa.Text(), nullable=False),
            sa.Column("tenant_id", sa.Text(), nullable=False),
            sa.Column("case_id", sa.Text(), nullable=True),
            sa.Column("source_id", sa.Text(), nullable=False),
            sa.Column("source_kind", sa.Text(), nullable=False),
            sa.Column("target_id", sa.Text(), nullable=False),
            sa.Column("target_kind", sa.Text(), nullable=False),
            sa.Column("relation", sa.Text(), nullable=False),
            sa.Column("signal_class", sa.Text(), nullable=False),
            sa.Column("evidence_id", sa.Text(), nullable=False),
            sa.Column("source_authority", sa.Text(), nullable=False),
            sa.Column("confidence_micros", sa.Integer(), nullable=False),
            sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True),
            sa.Column("supersedes_edge_id", sa.Text(), nullable=True),
            sa.Column("contradicts_edge_ids_json", sa.JSON(), nullable=False),
            sa.Column("attributes_json", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("tenant_id", "edge_id", name="uq_hippograph_journey_edge_tenant"),
        )
        inspector = sa.inspect(bind)
    else:
        actual = {column["name"] for column in inspector.get_columns("hippograph_journey_edges")}
        missing = sorted(_EXPECTED_COLUMNS - actual)
        if missing:
            raise RuntimeError(
                "existing hippograph_journey_edges is incompatible; missing columns: "
                + ", ".join(missing)
            )

    indexes = {row["name"] for row in inspector.get_indexes("hippograph_journey_edges")}
    if "ix_hippograph_journey_case_time" not in indexes:
        op.create_index(
            "ix_hippograph_journey_case_time",
            "hippograph_journey_edges",
            ["tenant_id", "case_id", "observed_at"],
        )


def downgrade() -> None:
    op.drop_index("ix_hippograph_journey_case_time", table_name="hippograph_journey_edges")
    op.drop_table("hippograph_journey_edges")
