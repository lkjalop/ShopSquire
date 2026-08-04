"""Add tenant-safe Party and rebuildable account intelligence foundations.

Revision ID: 20260810_account_intelligence
Revises: 20260809_authoritative_feed
"""
from alembic import op
import sqlalchemy as sa


revision = "20260810_account_intelligence"
down_revision = "20260809_authoritative_feed"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "party" not in tables:
        op.create_table(
            "party",
            sa.Column("id", sa.Text(), primary_key=True),
            sa.Column("tenant_id", sa.Text(), nullable=False),
            sa.Column("party_type", sa.Text(), nullable=False),
            sa.Column("display_name", sa.Text()),
            sa.Column("status", sa.Text(), nullable=False, server_default="active"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
        op.create_index("ix_party_tenant_type", "party", ["tenant_id", "party_type"])
    if "party_external_identity" not in tables:
        op.create_table(
            "party_external_identity",
            sa.Column("id", sa.Text(), primary_key=True),
            sa.Column("tenant_id", sa.Text(), nullable=False),
            sa.Column("party_id", sa.Text(), nullable=False),
            sa.Column("source", sa.Text(), nullable=False),
            sa.Column("object_type", sa.Text(), nullable=False),
            sa.Column("external_id", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["party_id"], ["party.id"]),
            sa.UniqueConstraint(
                "tenant_id", "source", "object_type", "external_id",
                name="uq_party_external_identity_scope",
            ),
        )
        op.create_index(
            "ix_party_external_identity_party",
            "party_external_identity",
            ["tenant_id", "party_id"],
        )
    if "party_relationship" not in tables:
        op.create_table(
            "party_relationship",
            sa.Column("id", sa.Text(), primary_key=True),
            sa.Column("tenant_id", sa.Text(), nullable=False),
            sa.Column("from_party_id", sa.Text(), nullable=False),
            sa.Column("to_party_id", sa.Text(), nullable=False),
            sa.Column("relationship_type", sa.Text(), nullable=False),
            sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("valid_to", sa.DateTime(timezone=True)),
            sa.ForeignKeyConstraint(["from_party_id"], ["party.id"]),
            sa.ForeignKeyConstraint(["to_party_id"], ["party.id"]),
        )
        op.create_index(
            "ix_party_relationship_scope",
            "party_relationship",
            ["tenant_id", "from_party_id", "relationship_type"],
        )
    if "account_observation" not in tables:
        op.create_table(
            "account_observation",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("tenant_id", sa.Text(), nullable=False),
            sa.Column("party_id", sa.Text(), nullable=False),
            sa.Column("source", sa.Text(), nullable=False),
            sa.Column("attribute_name", sa.Text(), nullable=False),
            sa.Column("value_json", sa.Text(), nullable=False),
            sa.Column("confidence", sa.Float(), nullable=False),
            sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("provenance_ref", sa.Text()),
            sa.ForeignKeyConstraint(["party_id"], ["party.id"]),
        )
        op.create_index(
            "ix_account_observation_tenant_party",
            "account_observation",
            ["tenant_id", "party_id", "occurred_at"],
        )
    if "account_activity" not in tables:
        op.create_table(
            "account_activity",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("tenant_id", sa.Text(), nullable=False),
            sa.Column("party_id", sa.Text(), nullable=False),
            sa.Column("activity_type", sa.Text(), nullable=False),
            sa.Column("external_ref", sa.Text(), nullable=False),
            sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("amount_cents", sa.Integer()),
            sa.Column("currency", sa.Text()),
            sa.Column("payload_json", sa.Text(), nullable=False),
            sa.ForeignKeyConstraint(["party_id"], ["party.id"]),
        )
        op.create_index(
            "ix_account_activity_tenant_party",
            "account_activity",
            ["tenant_id", "party_id", "occurred_at"],
        )
    if "account_intelligence_snapshot" not in tables:
        op.create_table(
            "account_intelligence_snapshot",
            sa.Column("id", sa.Text(), primary_key=True),
            sa.Column("tenant_id", sa.Text(), nullable=False),
            sa.Column("party_id", sa.Text(), nullable=False),
            sa.Column("measures_json", sa.Text(), nullable=False),
            sa.Column("source_watermark", sa.Text()),
            sa.Column("rebuilt_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["party_id"], ["party.id"]),
            sa.UniqueConstraint(
                "tenant_id", "party_id", name="uq_account_snapshot_tenant_party"
            ),
        )
    if "identity_resolution_decision" not in tables:
        op.create_table(
            "identity_resolution_decision",
            sa.Column("id", sa.Text(), primary_key=True),
            sa.Column("tenant_id", sa.Text(), nullable=False),
            sa.Column("decision_type", sa.Text(), nullable=False),
            sa.Column("left_party_id", sa.Text(), nullable=False),
            sa.Column("right_party_id", sa.Text(), nullable=False),
            sa.Column("status", sa.Text(), nullable=False, server_default="proposed"),
            sa.Column("evidence_json", sa.Text(), nullable=False),
            sa.Column("proposed_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("resolved_at", sa.DateTime(timezone=True)),
            sa.Column("resolved_by", sa.Text()),
        )
        op.create_index(
            "ix_identity_resolution_tenant_status",
            "identity_resolution_decision",
            ["tenant_id", "status", "proposed_at"],
        )


def downgrade() -> None:
    # Identity history and account activities are retained for audit.
    return
