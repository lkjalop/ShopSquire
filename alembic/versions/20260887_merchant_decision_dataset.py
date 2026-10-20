"""Immutable scoped input snapshots for read-only merchant decisions."""
from alembic import op
import sqlalchemy as sa

revision = '20260887_merchant_decision_dataset'
down_revision = '20260886_inventory_expiry'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('merchant_decision_dataset',
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('tenant_id', sa.String(128), nullable=False),
        sa.Column('sku', sa.String(255), nullable=False),
        sa.Column('as_of', sa.Text(), nullable=False),
        sa.Column('document_json', sa.Text(), nullable=False),
        sa.Column('created_at', sa.Text(), nullable=False))
    op.create_index('ix_merchant_dataset_scope', 'merchant_decision_dataset', ['tenant_id','sku','as_of'])


def downgrade():
    op.drop_index('ix_merchant_dataset_scope', table_name='merchant_decision_dataset')
    op.drop_table('merchant_decision_dataset')
