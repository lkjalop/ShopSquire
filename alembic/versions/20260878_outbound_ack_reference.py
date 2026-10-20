"""Keep acknowledgement identity separate from the transport receipt."""
from alembic import op
import sqlalchemy as sa

revision = '20260878_outbound_ack_reference'
down_revision = '20260877_outbound_effect_binding'
branch_labels = None
depends_on = None


def upgrade():
    columns = {c['name'] for c in sa.inspect(op.get_bind()).get_columns('outbound_message')}
    if 'ack_reference' not in columns:
        op.add_column('outbound_message', sa.Column('ack_reference', sa.Text(), nullable=True))


def downgrade():
    op.drop_column('outbound_message', 'ack_reference')
