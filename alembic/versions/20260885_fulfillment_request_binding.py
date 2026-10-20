"""Bind supplier continuation replay to the exact buyer request."""
from alembic import op
import sqlalchemy as sa

revision='20260885_fulfillment_request_binding'
down_revision='20260884_outbound_recovery'
branch_labels=None
depends_on=None


def upgrade():
    op.add_column('shopping_case_fulfillment_selections',sa.Column('request_digest',sa.Text(),nullable=True))


def downgrade():
    with op.batch_alter_table('shopping_case_fulfillment_selections') as batch:
        batch.drop_column('request_digest')
