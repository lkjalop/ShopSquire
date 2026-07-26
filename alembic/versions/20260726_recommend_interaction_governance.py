"""Authoritative tenant and consent identity for recommendation interactions.

Revision ID: 20260726_reco_interaction
Revises: 20260725_forecast_pairs
"""
from alembic import op
import sqlalchemy as sa


revision = "20260726_reco_interaction"
down_revision = "20260725_forecast_pairs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "recommend_interactions" not in tables:
        op.create_table(
            "recommend_interactions",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("event_time", sa.DateTime(timezone=True), nullable=False,
                      server_default=sa.func.current_timestamp()),
            sa.Column("tenant_id", sa.String(128), nullable=False),
            sa.Column("consent_state", sa.String(32), nullable=False),
            sa.Column("uid_hash", sa.String(128)),
            sa.Column("sku", sa.String(192)),
            sa.Column("action", sa.String(48), nullable=False),
            sa.Column("surface", sa.String(96)),
            sa.Column("trace_id", sa.String(128)),
            sa.Column("context_json", sa.Text()),
        )
    else:
        columns = {column["name"] for column in inspector.get_columns("recommend_interactions")}
        if "tenant_id" not in columns:
            op.add_column("recommend_interactions", sa.Column(
                "tenant_id", sa.String(128), nullable=True))
        if "consent_state" not in columns:
            op.add_column("recommend_interactions", sa.Column(
                "consent_state", sa.String(32), nullable=True))

    indexes = {index["name"] for index in sa.inspect(bind).get_indexes(
        "recommend_interactions")}
    if "ix_recommend_interactions_tenant_time" not in indexes:
        op.create_index(
            "ix_recommend_interactions_tenant_time",
            "recommend_interactions",
            ["tenant_id", "event_time"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "recommend_interactions" not in set(inspector.get_table_names()):
        return
    indexes = {index["name"] for index in inspector.get_indexes("recommend_interactions")}
    if "ix_recommend_interactions_tenant_time" in indexes:
        op.drop_index("ix_recommend_interactions_tenant_time", table_name="recommend_interactions")
