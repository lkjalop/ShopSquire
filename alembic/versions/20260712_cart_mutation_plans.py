"""cart_mutation_plans (V2 cart lane C1 / P0.4) — the prod-parity path for the plan table
cart_mutation_service._ensure_plans_table() creates at runtime for sqlite/dev. DDL kept
textually consistent with the service (a drift test enforces it). Indexes per GPT-5.6 review-6
#6: (tenant_id, uid, status) for the shopper-cart lookup, expires_at for the TTL sweep,
trace_id for decision-trace correlation. Idempotent; chains off the current head.
"""
from alembic import op

revision = "20260712_cart_mutation_plans"
down_revision = "20260711_taxonomy_grounding"
branch_labels = None
depends_on = None

TABLE_STATEMENTS = (
    """
CREATE TABLE IF NOT EXISTS cart_mutation_plans (
    id           TEXT PRIMARY KEY,
    tenant_id    TEXT NOT NULL,
    uid          TEXT NOT NULL,
    trace_id     TEXT,
    query        TEXT,
    plan         TEXT NOT NULL,
    risk         TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'proposed',
    cart_hash    TEXT NOT NULL,
    cart_version INTEGER NOT NULL DEFAULT 0,
    result       TEXT,
    created_at   TEXT DEFAULT CURRENT_TIMESTAMP,
    expires_at   TEXT,
    applied_at   TEXT
)
""",
    "CREATE INDEX IF NOT EXISTS ix_cmp_owner_status ON cart_mutation_plans(tenant_id, uid, status)",
    "CREATE INDEX IF NOT EXISTS ix_cmp_expires ON cart_mutation_plans(expires_at)",
    "CREATE INDEX IF NOT EXISTS ix_cmp_trace ON cart_mutation_plans(trace_id)",
)


def upgrade() -> None:
    for stmt in TABLE_STATEMENTS:
        op.execute(stmt)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_cmp_trace")
    op.execute("DROP INDEX IF EXISTS ix_cmp_expires")
    op.execute("DROP INDEX IF EXISTS ix_cmp_owner_status")
    op.execute("DROP TABLE IF EXISTS cart_mutation_plans")
