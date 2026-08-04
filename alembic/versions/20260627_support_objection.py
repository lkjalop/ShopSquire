"""Support-objection source (prod-parity) — support_objection.

A buyer objection on a theme; the market-signal backfill feeds detect_objection_cluster on REAL data.
Created at runtime via support_objection_source.ensure_table; this is the prod-parity path. Idempotent.
Chains off competitor_observation.
"""
from alembic import op

revision = "20260627_support_objection"
down_revision = "20260627_competitor_observation"
branch_labels = None
depends_on = None

TABLE_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS support_objection (
        id TEXT PRIMARY KEY,
        tenant_id TEXT DEFAULT 'default',
        theme TEXT,
        entity_ref TEXT,
        raised_at TEXT,
        source TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """,
)
INDEX_STATEMENTS = (
    "CREATE INDEX IF NOT EXISTS ix_support_objection_theme ON support_objection(tenant_id, theme)",
)
_DROP_TABLES = ("support_objection",)


def upgrade() -> None:
    for stmt in TABLE_STATEMENTS:
        op.execute(stmt)
    for stmt in INDEX_STATEMENTS:
        op.execute(stmt)


def downgrade() -> None:
    for tbl in _DROP_TABLES:
        op.execute(f"DROP TABLE IF EXISTS {tbl}")
