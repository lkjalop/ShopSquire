"""Persist immutable procurement decision snapshots and stage receipts.

Revision ID: 20260867_procurement_decision_runs
Revises: 20260866_agent_run_sequence
"""
from alembic import op


revision = "20260867_procurement_decision_runs"
down_revision = "20260866_agent_run_sequence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS procurement_decision_runs (
          id TEXT PRIMARY KEY,
          run_id TEXT NOT NULL,
          tenant_id TEXT NOT NULL,
          case_id TEXT NOT NULL,
          case_revision INTEGER NOT NULL,
          idempotency_key TEXT NOT NULL,
          knowledge_cutoff TIMESTAMP NOT NULL,
          evaluation_time TIMESTAMP NOT NULL,
          status TEXT NOT NULL,
          state_hash TEXT NOT NULL,
          payload_hash TEXT NOT NULL,
          payload_json JSON NOT NULL,
          created_at TIMESTAMP NOT NULL,
          CONSTRAINT uq_procurement_decision_run_tenant UNIQUE (tenant_id, run_id),
          CONSTRAINT uq_procurement_decision_run_idempotency
            UNIQUE (tenant_id, case_id, idempotency_key)
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_procurement_decision_runs_case_revision
        ON procurement_decision_runs (tenant_id, case_id, case_revision)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS procurement_decision_runs")
