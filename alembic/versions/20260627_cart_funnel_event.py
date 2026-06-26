"""Funnel source (prod-parity) — cart_funnel_event.

A purchase-funnel stage snapshot (entered/abandoned); the market-signal backfill feeds
detect_funnel_dropoff on REAL data. Created at runtime via funnel_source.ensure_table; this is the
prod-parity path. Idempotent. Chains off support_objection.
"""
from alembic import op

revision = "20260627_cart_funnel_event"
down_revision = "20260627_support_objection"
branch_labels = None
depends_on = None

TABLE_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS cart_funnel_event (
        id TEXT PRIMARY KEY,
        tenant_id TEXT DEFAULT 'default',
        stage TEXT,
        entered INTEGER DEFAULT 0,
        abandoned INTEGER DEFAULT 0,
        observed_at TEXT,
        source TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """,
)
INDEX_STATEMENTS = (
    "CREATE INDEX IF NOT EXISTS ix_cart_funnel_stage ON cart_funnel_event(tenant_id, stage)",
)
_DROP_TABLES = ("cart_funnel_event",)


def upgrade() -> None:
    for stmt in TABLE_STATEMENTS:
        op.execute(stmt)
    for stmt in INDEX_STATEMENTS:
        op.execute(stmt)


def downgrade() -> None:
    for tbl in _DROP_TABLES:
        op.execute(f"DROP TABLE IF EXISTS {tbl}")
