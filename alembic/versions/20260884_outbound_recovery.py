"""Audited operator observations of uncertain supplier sends."""
from alembic import op
import sqlalchemy as sa

revision = '20260884_outbound_recovery'
down_revision = '20260883_person_effect_approval'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('outbound_recovery_observation',
        sa.Column('tenant_id', sa.String(128), primary_key=True),
        sa.Column('message_id', sa.String(200), primary_key=True),
        sa.Column('operator_principal', sa.String(64), nullable=False),
        sa.Column('outcome', sa.String(32), nullable=False),
        sa.Column('evidence_ref', sa.Text(), nullable=False),
        sa.Column('provider_ref', sa.Text(), nullable=False),
        sa.Column('payload_digest', sa.String(64), nullable=False),
        sa.Column('observed_at', sa.Text(), nullable=False))


def downgrade():
    op.drop_table('outbound_recovery_observation')
