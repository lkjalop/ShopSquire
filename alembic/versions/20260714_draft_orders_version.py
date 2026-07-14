"""Add the optimistic-lock version to existing draft carts.

Fresh databases already receive this column from models/db.py. This migration repairs databases
created before cart mutation plans began comparing cart versions.
"""
from alembic import op
import sqlalchemy as sa

revision = "20260714_draft_orders_version"
down_revision = "20260713_draft_orders_tenant"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("draft_orders")}
    if "version" not in columns:
        op.add_column(
            "draft_orders",
            sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("0")),
        )


def downgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("draft_orders")}
    if "version" in columns:
        op.drop_column("draft_orders", "version")
