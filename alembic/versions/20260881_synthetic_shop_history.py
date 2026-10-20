"""Persist reproducible fictional-shop operational history."""

from alembic import op
import sqlalchemy as sa

revision = "20260881_synthetic_shop_history"
down_revision = "20260880_case_contract_selection"
branch_labels = None
depends_on = None


def upgrade():
    if not sa.inspect(op.get_bind()).has_table("synthetic_shop_history"):
        op.create_table(
            "synthetic_shop_history",
            sa.Column("tenant_id", sa.String(128), primary_key=True),
            sa.Column("sku", sa.String(255), primary_key=True),
            sa.Column("scenario_id", sa.String(128), primary_key=True),
            sa.Column("fixture_digest", sa.String(64), nullable=False),
            sa.Column("events_json", sa.Text(), nullable=False),
            sa.Column("recorded_at", sa.String(64), nullable=False),
        )


def downgrade():
    op.drop_table("synthetic_shop_history")
