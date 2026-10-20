"""Bind queued refunds to expiring, revocable exact-effect permits."""
from alembic import op
import sqlalchemy as sa

revision = '20260879_refund_effect_permit'
down_revision = '20260878_outbound_ack_reference'
branch_labels = None
depends_on = None
preserve_history_on_downgrade = True


def upgrade():
    columns = {c['name'] for c in sa.inspect(op.get_bind()).get_columns('refund_executions')}
    for name, kind in [('effect_digest', sa.Text()), ('authorized_until', sa.Float()), ('revoked_at', sa.Float())]:
        if name not in columns:
            op.add_column('refund_executions', sa.Column(name, kind, nullable=True))
    # Existing queued effects have no inferred authorization and fail closed.


def downgrade():
    raise RuntimeError('Refund permit removal requires explicit data migration and renewed authorization.')
