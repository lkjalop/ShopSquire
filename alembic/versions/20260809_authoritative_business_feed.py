"""Add append-only authoritative business observations and feed runs.

Revision ID: 20260809_authoritative_feed
Revises: 20260808_connector_reliability
"""
from alembic import op
import sqlalchemy as sa


revision = "20260809_authoritative_feed"
down_revision = "20260808_connector_reliability"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "authoritative_feed_run" not in tables:
        op.create_table(
            "authoritative_feed_run",
            sa.Column("id", sa.Text(), primary_key=True),
            sa.Column("tenant_id", sa.Text(), nullable=False),
            sa.Column("source", sa.Text(), nullable=False),
            sa.Column("status", sa.Text(), nullable=False),
            sa.Column("records_seen", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("records_inserted", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("records_replayed", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("error", sa.Text()),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("finished_at", sa.DateTime(timezone=True)),
        )
        op.create_index(
            "ix_authoritative_feed_run_tenant_source",
            "authoritative_feed_run",
            ["tenant_id", "source", "started_at"],
        )
    if "authoritative_business_observation" not in tables:
        op.create_table(
            "authoritative_business_observation",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("tenant_id", sa.Text(), nullable=False),
            sa.Column("source", sa.Text(), nullable=False),
            sa.Column("entity_type", sa.Text(), nullable=False),
            sa.Column("external_id", sa.Text(), nullable=False),
            sa.Column("event_time", sa.DateTime(timezone=True), nullable=False),
            sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("payload_hash", sa.String(64), nullable=False),
            sa.Column("payload_json", sa.Text(), nullable=False),
            sa.Column("quality_status", sa.Text(), nullable=False, server_default="accepted"),
            sa.Column("feed_run_id", sa.Text(), nullable=False),
            sa.ForeignKeyConstraint(["feed_run_id"], ["authoritative_feed_run.id"]),
        )
        op.create_index(
            "ix_authoritative_observation_tenant_entity_time",
            "authoritative_business_observation",
            ["tenant_id", "entity_type", "event_time"],
        )
        op.create_index(
            "ix_authoritative_observation_external",
            "authoritative_business_observation",
            ["tenant_id", "source", "entity_type", "external_id"],
        )


def downgrade() -> None:
    # Observations may be financial or custody evidence and are retained.
    return
