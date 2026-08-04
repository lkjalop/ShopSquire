"""Fulfilment case + bitemporal version tables (prod-parity for the runtime-ensured set).

The procurement workflow's durable state: fulfillment_case (identity + current status) and
fulfillment_case_version (one immutable bitemporally-versioned row per transition). Created at runtime
via repository.ensure_tables(); this is the prod-parity path. Idempotent (CREATE ... IF NOT EXISTS) so
re-running or a partially-migrated DB is safe. Chains off the market-autonomy head.
"""
from alembic import op

revision = "20260626_fulfillment"
down_revision = "20260626_market_autonomy"
branch_labels = None
depends_on = None

TABLE_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS fulfillment_case (
        id TEXT PRIMARY KEY,
        tenant_id TEXT DEFAULT 'default',
        buyer_uid_hash TEXT,
        source_trace_id TEXT,
        status TEXT,
        requested_by TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS fulfillment_case_version (
        id TEXT PRIMARY KEY,
        case_id TEXT,
        tenant_id TEXT DEFAULT 'default',
        schema_version INTEGER DEFAULT 1,
        state TEXT,
        state_json TEXT,
        event TEXT,
        reason_code TEXT,
        actor_type TEXT,
        actor_id TEXT,
        idempotency_key TEXT,
        evidence_json TEXT,
        valid_from TEXT,
        valid_to TEXT,
        system_from TEXT,
        system_to TEXT,
        supersedes_version_id TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """,
)
INDEX_STATEMENTS = (
    "CREATE INDEX IF NOT EXISTS ix_fc_case_status ON fulfillment_case(tenant_id, status)",
    "CREATE INDEX IF NOT EXISTS ix_fcv_open ON fulfillment_case_version(case_id, valid_to)",
    "CREATE INDEX IF NOT EXISTS ix_fcv_idem ON fulfillment_case_version(case_id, event, idempotency_key)",
)
_DROP_TABLES = ("fulfillment_case_version", "fulfillment_case")


def upgrade() -> None:
    for stmt in TABLE_STATEMENTS:
        op.execute(stmt)
    for stmt in INDEX_STATEMENTS:
        op.execute(stmt)


def downgrade() -> None:
    for tbl in _DROP_TABLES:
        op.execute(f"DROP TABLE IF EXISTS {tbl}")
