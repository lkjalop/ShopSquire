"""Make canonical market-fact quarantine idempotent.

Revision ID: 20260723_market_fact_quarantine_dedup
Revises: 20260722_market_fact_governance
"""
from alembic import op


revision = "20260723_market_fact_quarantine_dedup"
down_revision = "20260722_market_fact_governance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        DELETE FROM market_fact_quarantine
        WHERE id IN (
            SELECT id FROM (
                SELECT id, ROW_NUMBER() OVER (
                    PARTITION BY tenant_id, family, deduplication_id, reason_code
                    ORDER BY quarantined_at, id
                ) AS duplicate_number
                FROM market_fact_quarantine
            ) duplicates
            WHERE duplicate_number > 1
        )
    """)
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_market_fact_quarantine_dedup
        ON market_fact_quarantine(tenant_id, family, deduplication_id, reason_code)
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_market_fact_quarantine_dedup")
