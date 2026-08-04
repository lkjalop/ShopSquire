"""Persist governed public-market fetch revisions and cache metadata.

Revision ID: 20260818_public_market_fetch
Revises: 20260817_supply_intelligence
"""
from alembic import op
import sqlalchemy as sa


revision = "20260818_public_market_fetch"
down_revision = "20260817_supply_intelligence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "market_source_fetch_revision" in tables:
        return
    op.create_table(
        "market_source_fetch_revision",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("source_id", sa.Text(), nullable=False),
        sa.Column("request_key", sa.String(64), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("request_json", sa.Text(), nullable=False),
        sa.Column("outcome", sa.Text(), nullable=False),
        sa.Column("http_status", sa.Integer()),
        sa.Column("etag", sa.Text()),
        sa.Column("last_modified", sa.Text()),
        sa.Column("content_sha256", sa.String(64)),
        sa.Column("normalized_json", sa.Text()),
        sa.Column("source_policy_json", sa.Text(), nullable=False),
        sa.Column("error_code", sa.Text()),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "source_id",
            "request_key",
            "revision_number",
            name="uq_market_source_fetch_revision",
        ),
    )
    op.create_index(
        "ix_market_source_fetch_latest",
        "market_source_fetch_revision",
        ["tenant_id", "source_id", "request_key", "revision_number"],
    )


def downgrade() -> None:
    # External evidence revisions are audit evidence and are retained.
    return
