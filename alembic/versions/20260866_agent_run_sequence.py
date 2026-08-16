"""Allocate deterministic AgentRunEvent sequence numbers across workers.

Revision ID: 20260866_agent_run_sequence
Revises: 20260865_agent_run_event
"""
from alembic import op


revision = "20260866_agent_run_sequence"
down_revision = "20260865_agent_run_event"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS agent_run_sequence (
          tenant_id TEXT NOT NULL, run_id TEXT NOT NULL,
          next_sequence INTEGER NOT NULL,
          PRIMARY KEY (tenant_id, run_id)
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS agent_run_sequence")
