"""Add immutable, tenant-scoped inventory reorder proposals.

Revision ID: 20260802_inventory_reorder
Revises: 20260801_email_ops
"""
from alembic import op
import sqlalchemy as sa


revision = "20260802_inventory_reorder"
down_revision = "20260801_email_ops"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "inventory_reorder_proposal" not in tables:
        op.create_table(
            "inventory_reorder_proposal",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("tenant_id", sa.String(128), nullable=False),
            sa.Column("sku", sa.String(255), nullable=False),
            sa.Column("supplier_id", sa.String(255), nullable=False),
            sa.Column("quantity", sa.Integer(), nullable=False),
            sa.Column("landed_unit_cost_cents", sa.Integer(), nullable=False),
            sa.Column("total_cost_cents", sa.BigInteger(), nullable=False),
            sa.Column("currency", sa.String(8), nullable=False),
            sa.Column("lead_time_days", sa.Float(), nullable=False),
            sa.Column("source_record_id", sa.String(512), nullable=False),
            sa.Column("proposal_hash", sa.String(64), nullable=False),
            sa.Column("payload_json", sa.Text(), nullable=False),
            sa.Column("status", sa.String(32), nullable=False, server_default="pending_approval"),
            sa.Column("approval_id", sa.String(64)),
            sa.Column("executed_po_id", sa.String(64)),
            sa.Column("created_by", sa.String(255), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("executed_at", sa.DateTime(timezone=True)),
            sa.UniqueConstraint(
                "tenant_id",
                "proposal_hash",
                name="uq_inventory_reorder_proposal_hash",
            ),
        )
    proposal_indexes = {
        item["name"] for item in sa.inspect(bind).get_indexes("inventory_reorder_proposal")
    }
    if "ix_inventory_reorder_proposal_status" not in proposal_indexes:
        op.create_index(
            "ix_inventory_reorder_proposal_status",
            "inventory_reorder_proposal",
            ["tenant_id", "status", "expires_at"],
        )

    if "purchase_orders" not in tables:
        op.create_table(
            "purchase_orders",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("tenant_id", sa.String(128), nullable=False, server_default="default"),
            sa.Column("reorder_proposal_id", sa.String(64)),
            sa.Column("supplier_id", sa.String(255)),
            sa.Column("sku", sa.String(255), nullable=False),
            sa.Column("quantity", sa.Integer(), nullable=False),
            sa.Column("unit_cost", sa.Float()),
            sa.Column("landed_unit_cost_cents", sa.Integer()),
            sa.Column("currency", sa.String(8)),
            sa.Column("status", sa.String(32), nullable=False, server_default="created"),
            sa.Column("expected_delivery", sa.Text()),
            sa.Column("approval_ticket_id", sa.String(64)),
            sa.Column("approved_by", sa.String(255)),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True)),
        )
    else:
        columns = {
            item["name"] for item in sa.inspect(bind).get_columns("purchase_orders")
        }
        for column in (
            sa.Column("tenant_id", sa.String(128), nullable=False, server_default="default"),
            sa.Column("reorder_proposal_id", sa.String(64)),
            sa.Column("currency", sa.String(8)),
            sa.Column("landed_unit_cost_cents", sa.Integer()),
        ):
            if column.name not in columns:
                op.add_column("purchase_orders", column)
    po_indexes = {item["name"] for item in sa.inspect(bind).get_indexes("purchase_orders")}
    if "uq_purchase_orders_reorder_proposal" not in po_indexes:
        op.create_index(
            "uq_purchase_orders_reorder_proposal",
            "purchase_orders",
            ["tenant_id", "reorder_proposal_id"],
            unique=True,
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "purchase_orders" in tables:
        indexes = {item["name"] for item in inspector.get_indexes("purchase_orders")}
        if "uq_purchase_orders_reorder_proposal" in indexes:
            op.drop_index(
                "uq_purchase_orders_reorder_proposal",
                table_name="purchase_orders",
            )
    if "inventory_reorder_proposal" in tables:
        indexes = {
            item["name"] for item in sa.inspect(bind).get_indexes("inventory_reorder_proposal")
        }
        if "ix_inventory_reorder_proposal_status" in indexes:
            op.drop_index(
                "ix_inventory_reorder_proposal_status",
                table_name="inventory_reorder_proposal",
            )
        op.drop_table("inventory_reorder_proposal")
