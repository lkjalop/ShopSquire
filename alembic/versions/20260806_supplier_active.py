"""Reconcile legacy suppliers with the governed supplier catalog.

Revision ID: 20260806_supplier_active
Revises: 20260805_operator_membership
"""
from alembic import op
import sqlalchemy as sa


revision = "20260806_supplier_active"
down_revision = "20260805_operator_membership"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "suppliers" not in tables:
        return
    columns = {
        item["name"] for item in sa.inspect(bind).get_columns("suppliers")
    }
    if "active" not in columns:
        op.add_column(
            "suppliers",
            sa.Column(
                "active",
                sa.Integer(),
                nullable=False,
                server_default="1",
            ),
        )


def downgrade() -> None:
    # Supplier lifecycle evidence is operationally material; keep the column.
    return
