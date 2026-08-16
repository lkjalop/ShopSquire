"""Durable sanitized model execution audit ledger.

Revision ID: 20260865_agent_run_event
Revises: 20260864_market_ingestion_observability
"""
import sqlalchemy as sa
from alembic import op


revision = "20260865_agent_run_event"
down_revision = "20260864_market_ingestion_observability"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Use SQLAlchemy's typed false expression rather than ``DEFAULT 0``.
    # SQLite accepts the integer spelling for BOOLEAN, while PostgreSQL
    # correctly rejects it as a datatype mismatch.
    op.create_table(
        "agent_run_event",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("run_id", sa.Text(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("occurred_at_ms", sa.BigInteger(), nullable=False),
        sa.Column("deployment_id", sa.Text(), nullable=False),
        sa.Column("model_artifact_id", sa.Text(), nullable=False),
        sa.Column("prompt_id", sa.Text(), nullable=False),
        sa.Column("prompt_version", sa.Text(), nullable=False),
        sa.Column("prompt_hash", sa.Text(), nullable=False),
        sa.Column("context_hash", sa.Text(), nullable=False),
        sa.Column("policy_version", sa.Text(), nullable=False),
        sa.Column("details_json", sa.Text(), nullable=False),
        sa.Column(
            "commercial_authority",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_agent_run_event_tenant_run
        ON agent_run_event(tenant_id, run_id, sequence)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS agent_run_event")
