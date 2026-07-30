"""Classify tenant ownership for legacy commerce subjects.

Revision ID: 20260831_legacy_commerce_tenant_ownership
Revises: 20260830_privacy_deletion_jobs
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260831_legacy_commerce_tenant_ownership"
down_revision = "20260830_privacy_deletion_jobs"
branch_labels = None
depends_on = None


TABLES = ("customers", "orders", "order_sessions")


def _table_names() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def _add_ownership_columns(table: str) -> None:
    existing = _columns(table)
    if "tenant_id" not in existing:
        op.add_column(table, sa.Column("tenant_id", sa.Text(), nullable=True))
    if "tenant_ownership_status" not in existing:
        op.add_column(
            table,
            sa.Column(
                "tenant_ownership_status",
                sa.Text(),
                nullable=False,
                server_default="unclassified",
            ),
        )
    op.create_index(
        f"ix_{table}_tenant_ownership",
        table,
        ["tenant_id", "tenant_ownership_status"],
        if_not_exists=True,
    )


def upgrade() -> None:
    tables = _table_names()
    for table in TABLES:
        if table in tables:
            _add_ownership_columns(table)

    # Orders inherit only an already persisted tenant-scoped draft. Payload,
    # header, customer id and email are intentionally not accepted as evidence.
    if {"orders", "draft_orders"}.issubset(tables) and "tenant_id" in _columns("draft_orders"):
        op.execute(
            """
            UPDATE orders
            SET tenant_id = (
                    SELECT d.tenant_id
                    FROM draft_orders d
                    WHERE d.id = orders.draft_order_id
                ),
                tenant_ownership_status = 'derived_from_tenant_draft'
            WHERE tenant_id IS NULL
              AND (
                    SELECT d.tenant_id
                    FROM draft_orders d
                    WHERE d.id = orders.draft_order_id
                  ) IS NOT NULL
            """
        )

    # Sessions inherit their authoritative order ownership.
    if {"order_sessions", "orders"}.issubset(tables):
        op.execute(
            """
            UPDATE order_sessions
            SET tenant_id = (
                    SELECT o.tenant_id
                    FROM orders o
                    WHERE o.id = order_sessions.order_id
                ),
                tenant_ownership_status = 'derived_from_tenant_order'
            WHERE tenant_id IS NULL
              AND (
                    SELECT o.tenant_id
                    FROM orders o
                    WHERE o.id = order_sessions.order_id
                  ) IS NOT NULL
            """
        )

    # A customer may be classified only when all classified orders agree on
    # exactly one tenant. Multi-tenant or evidence-free subjects remain blocked.
    if {"customers", "orders"}.issubset(tables):
        op.execute(
            """
            UPDATE customers
            SET tenant_id = (
                    SELECT MIN(o.tenant_id)
                    FROM orders o
                    WHERE o.customer_id = customers.id
                      AND o.tenant_id IS NOT NULL
                    HAVING COUNT(DISTINCT o.tenant_id) = 1
                ),
                tenant_ownership_status = 'derived_from_consistent_orders'
            WHERE tenant_id IS NULL
              AND (
                    SELECT COUNT(DISTINCT o.tenant_id)
                    FROM orders o
                    WHERE o.customer_id = customers.id
                      AND o.tenant_id IS NOT NULL
                  ) = 1
            """
        )


def downgrade() -> None:
    tables = _table_names()
    for table in reversed(TABLES):
        if table not in tables:
            continue
        op.drop_index(f"ix_{table}_tenant_ownership", table_name=table, if_exists=True)
        existing = _columns(table)
        if "tenant_ownership_status" in existing:
            op.drop_column(table, "tenant_ownership_status")
        if "tenant_id" in existing:
            op.drop_column(table, "tenant_id")
