"""Add order_items table for return fraud corroboration

Revision ID: 20260326_add_order_items
Revises: 20260325_prod_tasks_and_vectors
Create Date: 2026-03-26

Why: _corroborate_order() in returns.py queries order_items to detect
brand mismatches and missing purchase history. Without this table the
check degrades silently to db_unavailable and fraud signals are lost.

Schema follows Codex review recommendation: user_id denormalized onto
order_items for single-table lookup (long-term: join via orders.customer_id).
"""

from alembic import op
import sqlalchemy as sa

revision = "20260326_add_order_items"
down_revision = "20260325_prod_tasks_and_vectors"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Use CREATE TABLE IF NOT EXISTS so this is safe to re-run
    op.execute("""
        CREATE TABLE IF NOT EXISTS order_items (
            id TEXT PRIMARY KEY,
            order_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            sku TEXT NOT NULL,
            product_name TEXT,
            brand TEXT,
            quantity INTEGER NOT NULL DEFAULT 1,
            unit_price_cents INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (order_id) REFERENCES orders(id)
        )
    """)

    # Composite index for the hot query path in _corroborate_order()
    # WHERE user_id = :uid AND sku = :sku ORDER BY created_at DESC LIMIT 1
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_order_items_user_sku_created
            ON order_items(user_id, sku, created_at DESC)
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_order_items_order_id
            ON order_items(order_id)
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_order_items_user_sku_created")
    op.execute("DROP INDEX IF EXISTS ix_order_items_order_id")
    op.execute("DROP TABLE IF EXISTS order_items")
