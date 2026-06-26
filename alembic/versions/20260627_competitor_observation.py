"""Competitor price source (prod-parity) — competitor_observation.

A rival's price for one of our SKUs; the market-signal backfill joins it to price_book_entry (our
retail) and feeds detect_competitor_undercut on REAL data. Created at runtime via
competitor_source.ensure_table; this is the prod-parity path. Idempotent. Chains off catalog_entities.
"""
from alembic import op

revision = "20260627_competitor_observation"
down_revision = "20260626_catalog_entities"
branch_labels = None
depends_on = None

TABLE_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS competitor_observation (
        id TEXT PRIMARY KEY,
        tenant_id TEXT DEFAULT 'default',
        sku TEXT NOT NULL,
        competitor TEXT,
        competitor_price_cents INTEGER,
        observed_at TEXT,
        source TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """,
)
INDEX_STATEMENTS = (
    "CREATE INDEX IF NOT EXISTS ix_competitor_obs_sku ON competitor_observation(tenant_id, sku)",
)
_DROP_TABLES = ("competitor_observation",)


def upgrade() -> None:
    for stmt in TABLE_STATEMENTS:
        op.execute(stmt)
    for stmt in INDEX_STATEMENTS:
        op.execute(stmt)


def downgrade() -> None:
    for tbl in _DROP_TABLES:
        op.execute(f"DROP TABLE IF EXISTS {tbl}")
