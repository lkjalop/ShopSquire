"""draft_orders.tenant_id (R10.2 step 1 — additive, zero behavior change).

Cart identity becomes (tenant_id, customer_id). DEFAULT 'default' backfills every existing
row — exactly today's single-tenant truth. Reads/writes get tenant-scoped in the follow-up
threading step (docs/SHOPSQUIRE_V2_TENANT_CART_SPEC_2026-07-13.md), NEVER in this migration:
landing the column first lets it soak while behavior is unchanged, so the threading step can
be verified against a table that already carries the answer.

Index (tenant_id, customer_id, status) matches the threaded lookup shape. Idempotent both
paths (models/db.py in-code DDL adds the same column via guarded ALTER).
"""
from alembic import op

revision = "20260713_draft_orders_tenant"
down_revision = "20260712_cart_mutation_plans"
branch_labels = None
depends_on = None

STATEMENTS = (
    "ALTER TABLE draft_orders ADD COLUMN tenant_id TEXT NOT NULL DEFAULT 'default'",
    "CREATE INDEX IF NOT EXISTS ix_draft_orders_tenant_customer_status "
    "ON draft_orders (tenant_id, customer_id, status)",
)


def upgrade() -> None:
    for stmt in STATEMENTS:
        try:
            op.execute(stmt)
        except Exception:
            pass   # additive + idempotent: column/index may already exist (in-code DDL parity)


def downgrade() -> None:
    try:
        op.execute("DROP INDEX IF EXISTS ix_draft_orders_tenant_customer_status")
    except Exception:
        pass
    # SQLite can't DROP COLUMN portably pre-3.35; the column is additive with a default and
    # harmless to leave — downgrade removes only the index.
