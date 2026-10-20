"""Stable person bindings and exact-effect approval receipts."""
from alembic import op
import sqlalchemy as sa
revision='20260883_person_effect_approval'
down_revision='20260882_inventory_transactions'
branch_labels=None
depends_on=None


def upgrade():
    op.create_table('operator_person_binding',
        sa.Column('tenant_id',sa.String(128),primary_key=True),
        sa.Column('principal_hash',sa.String(64),primary_key=True),
        sa.Column('person_id',sa.String(200),nullable=False),
        sa.Column('assigned_by',sa.String(200),nullable=False),
        sa.Column('status',sa.String(32),nullable=False,server_default='active'))
    op.create_table('person_effect_approval',
        sa.Column('id',sa.String(64),primary_key=True),
        sa.Column('tenant_id',sa.String(128),nullable=False),
        sa.Column('requester_principal',sa.String(64),nullable=False),
        sa.Column('approver_principal',sa.String(64),nullable=False),
        sa.Column('requester_person',sa.String(200),nullable=False),
        sa.Column('approver_person',sa.String(200),nullable=False),
        sa.Column('value_cents',sa.Integer(),nullable=False),
        sa.Column('effect_digest',sa.String(64),nullable=False),
        sa.Column('effect_json',sa.Text(),nullable=False),
        sa.Column('issued_at',sa.Text(),nullable=False),
        sa.Column('expires_at',sa.Text(),nullable=False),
        sa.Column('revoked_at',sa.Text()),sa.Column('revoked_by',sa.Text()))
    columns={c['name'] for c in sa.inspect(op.get_bind()).get_columns('outbound_message')}
    if 'person_approval_id' not in columns:
        op.add_column('outbound_message',sa.Column('person_approval_id',sa.Text()))


def downgrade():
    with op.batch_alter_table('outbound_message') as batch:
        batch.drop_column('person_approval_id')
    op.drop_table('person_effect_approval')
    op.drop_table('operator_person_binding')
