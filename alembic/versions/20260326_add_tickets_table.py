"""Add tickets table for TicketingAgent persistence

Revision ID: 20260326_add_tickets
Revises: 20260326_add_order_items
Create Date: 2026-03-26

Why: ticketing.py INSERT statements target a 'tickets' table that was never
in any migration. Without this, every ticket silently falls back to an
in-memory dict that is lost on process restart. This migration makes ticket
persistence real so audit trails, approval flows, and SLA tracking work
across restarts and deployments.
"""

from alembic import op
import sqlalchemy as sa

revision = "20260326_add_tickets"
down_revision = "20260326_add_order_items"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS tickets (
            id TEXT PRIMARY KEY,
            external_id TEXT,
            title TEXT NOT NULL,
            description TEXT,
            severity TEXT NOT NULL DEFAULT 'medium',
            status TEXT NOT NULL DEFAULT 'open',
            approval_required INTEGER NOT NULL DEFAULT 0,
            trace_id TEXT,
            tenant_id TEXT,
            evidence TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Index for the hot list_tickets() query: ORDER BY created_at DESC
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_tickets_tenant_created
            ON tickets(tenant_id, created_at DESC)
    """)

    # Index for status-filtered queries
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_tickets_status
            ON tickets(status)
    """)

    # Index for trace_id lookups (approve_ticket bridging)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_tickets_trace_id
            ON tickets(trace_id)
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_tickets_tenant_created")
    op.execute("DROP INDEX IF EXISTS ix_tickets_status")
    op.execute("DROP INDEX IF EXISTS ix_tickets_trace_id")
    op.execute("DROP TABLE IF EXISTS tickets")
