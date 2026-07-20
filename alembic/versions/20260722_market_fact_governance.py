"""Quarantine untrusted canonical market facts.

Revision ID: 20260722_market_fact_governance
Revises: 20260721_market_fact_contract
"""
from alembic import op


revision = "20260722_market_fact_governance"
down_revision = "20260721_market_fact_contract"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS market_fact_quarantine (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            family TEXT NOT NULL,
            source_system TEXT,
            source_record_id TEXT,
            deduplication_id TEXT,
            reason_code TEXT NOT NULL,
            payload_json TEXT,
            quarantined_at TEXT NOT NULL
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_market_fact_quarantine_tenant "
               "ON market_fact_quarantine(tenant_id, quarantined_at)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_market_fact_quarantine_reason "
               "ON market_fact_quarantine(reason_code, source_system)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS market_fact_quarantine")
