"""Atomic receipts and transfers over existing location stock."""
from alembic import op
import sqlalchemy as sa

revision='20260888_inventory_stock_movements'
down_revision='20260887_merchant_decision_dataset'
branch_labels=None
depends_on=None


def upgrade():
    op.create_table('inventory_stock_movement',
        sa.Column('tenant_id',sa.String(128),primary_key=True),
        sa.Column('source_reference',sa.String(200),primary_key=True),
        sa.Column('kind',sa.String(32),nullable=False),
        sa.Column('sku',sa.String(255),nullable=False),
        sa.Column('source_location',sa.String(200)),
        sa.Column('destination_location',sa.String(200),nullable=False),
        sa.Column('quantity',sa.Integer(),nullable=False),
        sa.Column('payload_digest',sa.String(64),nullable=False),
        sa.Column('created_at',sa.DateTime(),server_default=sa.func.current_timestamp()))
    op.create_index('ix_stock_movement_scope','inventory_stock_movement',['tenant_id','sku'])


def downgrade():
    op.drop_index('ix_stock_movement_scope',table_name='inventory_stock_movement')
    op.drop_table('inventory_stock_movement')
