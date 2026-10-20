"""Persist optional reservation deadlines; legacy holds require explicit review."""
from alembic import op
import sqlalchemy as sa

revision='20260886_inventory_expiry'
down_revision='20260885_fulfillment_request_binding'
branch_labels=None
depends_on=None


def upgrade():
    op.add_column('inventory_reservation',sa.Column('expires_at',sa.Text(),nullable=True))
    op.create_index('ix_inventory_reservation_expiry','inventory_reservation',['tenant_id','status','expires_at'])


def downgrade():
    op.drop_index('ix_inventory_reservation_expiry',table_name='inventory_reservation')
    with op.batch_alter_table('inventory_reservation') as batch:
        batch.drop_column('expires_at')
