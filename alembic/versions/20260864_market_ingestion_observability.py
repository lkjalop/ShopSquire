"""Durable connector receipts, watermarks, and dead-letter replay.

Revision ID: 20260864_market_ingestion_observability
Revises: 20260863_hippograph_edges
"""
from alembic import op


revision = "20260864_market_ingestion_observability"
down_revision = "20260863_hippograph_edges"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS market_source_ingestion_run (
          id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, source TEXT NOT NULL,
          source_schema_version INTEGER, contract_schema_version TEXT NOT NULL,
          status TEXT NOT NULL, rows_read INTEGER NOT NULL DEFAULT 0,
          accepted INTEGER NOT NULL DEFAULT 0, outcomes_json TEXT NOT NULL,
          latency_ms REAL NOT NULL DEFAULT 0, watermark_before TEXT,
          watermark_after TEXT, error_code TEXT, started_at TEXT NOT NULL,
          finished_at TEXT NOT NULL
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_market_source_run_health
        ON market_source_ingestion_run(tenant_id, source, finished_at)
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS market_source_watermark (
          tenant_id TEXT NOT NULL, source TEXT NOT NULL,
          source_schema_version INTEGER, watermark TEXT,
          last_success_at TEXT, last_attempt_at TEXT NOT NULL,
          last_status TEXT NOT NULL, updated_at TEXT NOT NULL,
          PRIMARY KEY (tenant_id, source)
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS market_source_dead_letter (
          id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, source TEXT NOT NULL,
          dedup_key TEXT, source_schema_version INTEGER,
          reason_code TEXT NOT NULL, envelope_json TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0,
          first_failed_at TEXT NOT NULL, last_attempt_at TEXT,
          resolved_at TEXT, resolution TEXT
        )
    """)
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS ux_market_source_dead_letter
        ON market_source_dead_letter(tenant_id, source, dedup_key, reason_code)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_market_source_dead_letter_pending
        ON market_source_dead_letter(tenant_id, status, first_failed_at)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS market_source_dead_letter")
    op.execute("DROP TABLE IF EXISTS market_source_watermark")
    op.execute("DROP TABLE IF EXISTS market_source_ingestion_run")
