"""Atomic reservations and their idempotent stock-effect history."""
from alembic import op
import sqlalchemy as sa
revision='20260882_inventory_transactions'
down_revision='20260881_synthetic_shop_history'
branch_labels=None
depends_on=None


def upgrade():
    op.create_table('inventory_reservation',
        sa.Column('tenant_id',sa.String(128),primary_key=True),
        sa.Column('reservation_id',sa.String(200),primary_key=True),
        sa.Column('sku',sa.String(255),nullable=False),
        sa.Column('location_id',sa.String(200),nullable=False),
        sa.Column('quantity',sa.Integer(),nullable=False),
        sa.Column('status',sa.String(32),nullable=False),
        sa.Column('returned_quantity',sa.Integer(),nullable=False,server_default='0'),
        sa.Column('payload_digest',sa.String(64),nullable=False),
        sa.Column('created_at',sa.TIMESTAMP(),server_default=sa.func.current_timestamp()))
    op.create_table('inventory_effect_event',
        sa.Column('tenant_id',sa.String(128),primary_key=True),
        sa.Column('event_id',sa.String(200),primary_key=True),
        sa.Column('reservation_id',sa.String(200),nullable=False),
        sa.Column('kind',sa.String(32),nullable=False),
        sa.Column('quantity',sa.Integer(),nullable=False),
        sa.Column('payload_digest',sa.String(64),nullable=False),
        sa.Column('on_hand_delta',sa.Integer(),nullable=False),
        sa.Column('reserved_delta',sa.Integer(),nullable=False),
        sa.Column('created_at',sa.TIMESTAMP(),server_default=sa.func.current_timestamp()))


def downgrade():
    op.drop_table('inventory_effect_event')
    op.drop_table('inventory_reservation')
