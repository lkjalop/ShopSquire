"""add purchase_date and warranty_months to orders

Revision ID: 20260310_order_warranty_fields
Revises: 20260217_session_id
Create Date: 2026-03-10 00:00:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260310_order_warranty_fields"
down_revision = "20260217_session_id"
branch_labels = None
depends_on = None


def _has_column(table: str, col: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    try:
        cols = insp.get_columns(table)
    except Exception:
        return False
    return any(str(c.get("name") or "") == col for c in cols)


def upgrade() -> None:
    if not _has_column("orders", "purchase_date"):
        with op.batch_alter_table("orders") as batch_op:
            batch_op.add_column(sa.Column("purchase_date", sa.Date(), nullable=True))
    if not _has_column("orders", "warranty_months"):
        with op.batch_alter_table("orders") as batch_op:
            batch_op.add_column(sa.Column("warranty_months", sa.Integer(), nullable=True, server_default="12"))


def downgrade() -> None:
    if _has_column("orders", "warranty_months"):
        with op.batch_alter_table("orders") as batch_op:
            batch_op.drop_column("warranty_months")
    if _has_column("orders", "purchase_date"):
        with op.batch_alter_table("orders") as batch_op:
            batch_op.drop_column("purchase_date")
