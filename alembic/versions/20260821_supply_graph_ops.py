"""Add operational supply-graph revision and source-mapping semantics.

Revision ID: 20260821_supply_graph_ops
Revises: 20260820_inventory_projection
"""
from alembic import op
import sqlalchemy as sa


revision = "20260821_supply_graph_ops"
down_revision = "20260820_inventory_projection"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    if table not in set(inspector.get_table_names()):
        return set()
    return {str(column["name"]) for column in inspector.get_columns(table)}


def _add(table: str, name: str, column: sa.Column) -> None:
    if name not in _columns(table):
        op.add_column(table, column)


def upgrade() -> None:
    _add("supply_node", "logical_key", sa.Column("logical_key", sa.Text()))
    _add("supply_node", "recorded_from", sa.Column("recorded_from", sa.DateTime(timezone=True)))
    _add("supply_node", "recorded_to", sa.Column("recorded_to", sa.DateTime(timezone=True)))
    _add("supply_node", "supersedes_id", sa.Column("supersedes_id", sa.Text()))
    _add("supply_node", "revision_reason", sa.Column("revision_reason", sa.Text()))
    _add("supply_node", "identity_status", sa.Column(
        "identity_status", sa.Text(), nullable=False, server_default="resolved",
    ))

    _add("supply_dependency_edge", "logical_key", sa.Column("logical_key", sa.Text()))
    _add("supply_dependency_edge", "recorded_from", sa.Column(
        "recorded_from", sa.DateTime(timezone=True),
    ))
    _add("supply_dependency_edge", "recorded_to", sa.Column(
        "recorded_to", sa.DateTime(timezone=True),
    ))
    _add("supply_dependency_edge", "supersedes_id", sa.Column("supersedes_id", sa.Text()))
    _add("supply_dependency_edge", "revision_reason", sa.Column("revision_reason", sa.Text()))

    _add("supply_signal_observation", "mapping_id", sa.Column("mapping_id", sa.Text()))
    _add("supply_signal_observation", "comparison_scope_json", sa.Column(
        "comparison_scope_json", sa.Text(),
    ))
    _add("supply_signal_observation", "source_revision", sa.Column("source_revision", sa.Integer()))
    _add("supply_signal_observation", "expires_at", sa.Column(
        "expires_at", sa.DateTime(timezone=True),
    ))

    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "market_subject_mapping" not in tables:
        op.create_table(
            "market_subject_mapping",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("tenant_id", sa.Text(), nullable=False),
            sa.Column("source_id", sa.Text(), nullable=False),
            sa.Column("external_subject_id", sa.Text(), nullable=False),
            sa.Column("subject_node_id", sa.Text(), nullable=False),
            sa.Column("status", sa.Text(), nullable=False),
            sa.Column("mapping_basis", sa.Text(), nullable=False),
            sa.Column("provenance_json", sa.Text(), nullable=False),
            sa.Column("approved_by", sa.Text()),
            sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
            sa.Column("valid_to", sa.DateTime(timezone=True)),
            sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint(
                "tenant_id", "source_id", "external_subject_id", "subject_node_id",
                "valid_from", name="uq_market_subject_mapping_revision",
            ),
        )
        op.create_index(
            "ix_market_subject_mapping_lookup",
            "market_subject_mapping",
            ["tenant_id", "source_id", "external_subject_id", "status", "valid_to"],
        )

    if "supply_signal_quarantine" not in tables:
        op.create_table(
            "supply_signal_quarantine",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("tenant_id", sa.Text(), nullable=False),
            sa.Column("source_id", sa.Text(), nullable=False),
            sa.Column("source_record_id", sa.Text(), nullable=False),
            sa.Column("source_revision", sa.Integer(), nullable=False),
            sa.Column("external_subject_id", sa.Text(), nullable=False),
            sa.Column("reason", sa.Text(), nullable=False),
            sa.Column("observation_json", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint(
                "tenant_id", "source_id", "source_record_id", "source_revision",
                name="uq_supply_signal_quarantine_revision",
            ),
        )
        op.create_index(
            "ix_supply_signal_quarantine_scope",
            "supply_signal_quarantine",
            ["tenant_id", "source_id", "reason", "created_at"],
        )

    # Portable indexes intentionally avoid partial-index syntax. Repository
    # writes serialize current-revision closure and insertion transactionally.
    bind = op.get_bind()
    indexes = {
        str(index["name"])
        for index in sa.inspect(bind).get_indexes("supply_node")
    }
    if "ix_supply_node_logical_revision" not in indexes:
        op.create_index(
            "ix_supply_node_logical_revision",
            "supply_node",
            ["tenant_id", "logical_key", "recorded_to", "valid_to"],
        )
    indexes = {
        str(index["name"])
        for index in sa.inspect(bind).get_indexes("supply_dependency_edge")
    }
    if "ix_supply_edge_logical_revision" not in indexes:
        op.create_index(
            "ix_supply_edge_logical_revision",
            "supply_dependency_edge",
            ["tenant_id", "logical_key", "recorded_to", "valid_to"],
        )


def downgrade() -> None:
    # Bitemporal evidence and quarantined observations are retained for audit.
    return
