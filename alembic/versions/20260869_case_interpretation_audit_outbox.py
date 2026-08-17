"""Persist revision-bound interpretation and recommendation audit work.

Revision ID: 20260869_case_interpretation_audit
Revises: 20260868_decision_dependencies
"""
from alembic import op
import sqlalchemy as sa


revision = "20260869_case_interpretation_audit"
down_revision = "20260868_decision_dependencies"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("shopping_cases") as batch:
        batch.add_column(sa.Column(
            "revision", sa.Integer(), nullable=False, server_default="1",
        ))
    op.execute("""
        CREATE TABLE IF NOT EXISTS shopping_case_interpretation_jobs (
          job_id TEXT PRIMARY KEY,
          tenant_id TEXT NOT NULL,
          case_id TEXT NOT NULL,
          uid TEXT NOT NULL,
          case_revision INTEGER NOT NULL,
          plan_id TEXT NOT NULL,
          status TEXT NOT NULL,
          input_plan_json JSON NOT NULL,
          result_plan_json JSON,
          receipt_json JSON,
          task_id TEXT,
          attempts INTEGER NOT NULL DEFAULT 0,
          error_code TEXT,
          created_at TIMESTAMP NOT NULL,
          updated_at TIMESTAMP NOT NULL,
          completed_at TIMESTAMP,
          CONSTRAINT uq_case_interpretation_revision_plan
            UNIQUE (tenant_id, case_id, case_revision, plan_id)
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_case_interpretation_status
        ON shopping_case_interpretation_jobs (status, updated_at)
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS recommendation_audit_outbox (
          outbox_id TEXT PRIMARY KEY,
          tenant_id TEXT NOT NULL,
          trace_id TEXT NOT NULL,
          status TEXT NOT NULL,
          payload_json JSON NOT NULL,
          task_id TEXT,
          attempts INTEGER NOT NULL DEFAULT 0,
          error_code TEXT,
          created_at TIMESTAMP NOT NULL,
          updated_at TIMESTAMP NOT NULL,
          completed_at TIMESTAMP,
          CONSTRAINT uq_recommendation_audit_trace UNIQUE (tenant_id, trace_id)
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_recommendation_audit_status
        ON recommendation_audit_outbox (status, updated_at)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS recommendation_audit_outbox")
    op.execute("DROP TABLE IF EXISTS shopping_case_interpretation_jobs")
    with op.batch_alter_table("shopping_cases") as batch:
        batch.drop_column("revision")
