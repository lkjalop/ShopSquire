"""Bind queued approvals to exact message bytes; old unbound rows require review."""
from alembic import op
import sqlalchemy as sa

revision = '20260877_outbound_effect_binding'
down_revision = '20260876_dmarc_tenant_boundary'
branch_labels = None
depends_on = None
preserve_history_on_downgrade = True


def upgrade():
    columns = {c['name'] for c in sa.inspect(op.get_bind()).get_columns('outbound_message')}
    for name in ('effect_digest', 'permit_expires_at', 'permit_revoked_at'):
        if name not in columns:
            op.add_column('outbound_message', sa.Column(name, sa.Text(), nullable=True))


def downgrade():
    raise RuntimeError('Removing effect bindings requires an explicit data-preserving rollback plan')
