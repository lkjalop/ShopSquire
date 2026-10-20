"""Authenticated requests and exact person-approved inventory effects."""
from alembic import op
import sqlalchemy as sa

revision='20260889_operator_inventory_requests'
down_revision='20260888_inventory_stock_movements'
branch_labels=None
depends_on=None


def upgrade():
    op.create_table('operator_inventory_request',
        sa.Column('id',sa.String(64),primary_key=True),
        sa.Column('tenant_id',sa.String(128),nullable=False),
        sa.Column('source_reference',sa.String(200),nullable=False),
        sa.Column('requester_principal',sa.String(64),nullable=False),
        sa.Column('payload_json',sa.Text(),nullable=False),
        sa.Column('payload_digest',sa.String(64),nullable=False),
        sa.Column('value_cents',sa.Integer(),nullable=False),
        sa.Column('currency',sa.String(3),nullable=False),
        sa.Column('status',sa.String(32),nullable=False),
        sa.Column('approval_id',sa.String(64)),
        sa.Column('result_json',sa.Text()),
        sa.Column('created_at',sa.Text(),nullable=False),
        sa.UniqueConstraint('tenant_id','source_reference',name='uq_inventory_request_source'))


def downgrade():
    op.drop_table('operator_inventory_request')
