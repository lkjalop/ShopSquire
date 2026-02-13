"""add inventory sync tables (canonical sync log + external snapshots)

Revision ID: c4bda3ab2d11
Revises: 8d7f5a0df0d2
Create Date: 2026-02-08 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "c4bda3ab2d11"
down_revision = "8d7f5a0df0d2"
branch_labels = None
depends_on = None


def _has_table(name: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return bool(insp.has_table(name))


def _has_index(table: str, name: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    try:
        indexes = insp.get_indexes(table)
    except Exception:
        return False
    return any(i.get("name") == name for i in indexes)


def _create_table_if_missing(name: str, *cols: sa.Column, **kwargs) -> None:
    if _has_table(name):
        return
    op.create_table(name, *cols, **kwargs)


def upgrade() -> None:
    _create_table_if_missing(
        "inventory_sync_runs",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("tenant_id", sa.Text(), nullable=True),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="started"),
        sa.Column("started_at", sa.Text(), nullable=True, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("finished_at", sa.Text(), nullable=True),
        sa.Column("records_seen", sa.Integer(), nullable=True, server_default=sa.text("0")),
        sa.Column("records_applied", sa.Integer(), nullable=True, server_default=sa.text("0")),
        sa.Column("error", sa.Text(), nullable=True),
    )

    _create_table_if_missing(
        "inventory_external_stock",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("tenant_id", sa.Text(), nullable=True),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("sku", sa.Text(), nullable=False),
        sa.Column("warehouse", sa.Text(), nullable=True, server_default="default"),
        sa.Column("stock", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("observed_at", sa.Text(), nullable=True, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("raw_json", sa.Text(), nullable=True),
    )
    if _has_table("inventory_external_stock") and not _has_index("inventory_external_stock", "ix_inventory_external_stock_source_sku"):
        op.create_index("ix_inventory_external_stock_source_sku", "inventory_external_stock", ["source", "sku"])


def downgrade() -> None:
    pass
