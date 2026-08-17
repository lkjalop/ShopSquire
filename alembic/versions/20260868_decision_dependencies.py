"""Persist decision stage and artifact dependency edges.

Revision ID: 20260868_decision_dependencies
Revises: 20260867_procurement_decision_runs
"""
from alembic import op


revision = "20260868_decision_dependencies"
down_revision = "20260867_procurement_decision_runs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS procurement_decision_dependencies (
          edge_id TEXT PRIMARY KEY,
          run_id TEXT NOT NULL,
          tenant_id TEXT NOT NULL,
          case_id TEXT NOT NULL,
          source_ref TEXT NOT NULL,
          target_ref TEXT NOT NULL,
          relation TEXT NOT NULL,
          CONSTRAINT uq_decision_dependency_tenant UNIQUE (tenant_id, edge_id)
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_decision_dependencies_source
        ON procurement_decision_dependencies (tenant_id, case_id, source_ref)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_decision_dependencies_target
        ON procurement_decision_dependencies (tenant_id, case_id, target_ref)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS procurement_decision_dependencies")
