"""Add catalog attributes required by the V2 grounded recommender.

Revision ID: 20260824_catalog_grounding_parity
Revises: 20260823_supply_hypothesis_workflow
"""

from alembic import op
import sqlalchemy as sa


revision = "20260824_catalog_grounding_parity"
down_revision = "20260823_supply_hypothesis_workflow"
branch_labels = None
depends_on = None


def _columns() -> set[str]:
    inspector = sa.inspect(op.get_bind())
    if "products" not in set(inspector.get_table_names()):
        return set()
    return {
        str(column["name"])
        for column in inspector.get_columns("products")
    }


def _table_columns(table: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    if table not in set(inspector.get_table_names()):
        return set()
    return {
        str(column["name"])
        for column in inspector.get_columns(table)
    }


def upgrade() -> None:
    columns = _columns()
    for name in ("product_type", "brand", "category", "attributes"):
        if name not in columns:
            op.add_column("products", sa.Column(name, sa.Text()))
    supplier_columns = _table_columns("suppliers")
    if "preferred_channel" not in supplier_columns:
        op.add_column("suppliers", sa.Column("preferred_channel", sa.Text()))
    product_columns = _table_columns("supplier_products")
    additions = (
        ("moq", sa.Integer()),
        ("min_order_value_cents", sa.Integer()),
        ("lead_time_days", sa.Integer()),
        ("region", sa.Text()),
        ("on_time_rate", sa.Float()),
        ("price_breaks", sa.Text()),
        ("contract_status", sa.Text()),
        ("active", sa.Integer()),
    )
    for name, column_type in additions:
        if name not in product_columns:
            op.add_column(
                "supplier_products", sa.Column(name, column_type),
            )

    if "supplier_baseline_events" not in sa.inspect(op.get_bind()).get_table_names():
        op.create_table(
            "supplier_baseline_events",
            sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
            sa.Column("tenant_id", sa.Text(), nullable=False),
            sa.Column("sender_domain_hash", sa.Text(), nullable=False),
            sa.Column("event_ts", sa.Text(), nullable=False),
            sa.Column("hour_of_day", sa.Integer(), nullable=False),
            sa.Column("invoice_amount", sa.Float(), nullable=True),
            sa.Column(
                "attachment_count",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("0"),
            ),
            sa.Column(
                "created_at",
                sa.Text(),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
        )
        op.create_index(
            "idx_sbe_tenant_sender",
            "supplier_baseline_events",
            ["tenant_id", "sender_domain_hash"],
        )
        op.create_index(
            "idx_sbe_ts",
            "supplier_baseline_events",
            ["event_ts"],
        )


def downgrade() -> None:
    # These columns may predate Alembic in SQLite demo databases. Preserve
    # catalog evidence rather than deleting operator data during rollback.
    return
