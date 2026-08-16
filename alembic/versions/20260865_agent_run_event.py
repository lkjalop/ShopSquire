"""Durable sanitized model execution audit ledger.

Revision ID: 20260865_agent_run_event
Revises: 20260864_market_ingestion_observability
"""
from alembic import op


revision = "20260865_agent_run_event"
down_revision = "20260864_market_ingestion_observability"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS agent_run_event (
          id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, run_id TEXT NOT NULL,
          sequence INTEGER NOT NULL, event_type TEXT NOT NULL,
          occurred_at_ms BIGINT NOT NULL, deployment_id TEXT NOT NULL,
          model_artifact_id TEXT NOT NULL, prompt_id TEXT NOT NULL,
          prompt_version TEXT NOT NULL, prompt_hash TEXT NOT NULL,
          context_hash TEXT NOT NULL, policy_version TEXT NOT NULL,
          details_json TEXT NOT NULL, commercial_authority BOOLEAN NOT NULL DEFAULT 0
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_agent_run_event_tenant_run
        ON agent_run_event(tenant_id, run_id, sequence)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS agent_run_event")
