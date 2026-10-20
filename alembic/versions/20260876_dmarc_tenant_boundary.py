"""Establish DMARC ownership without assigning legacy data to an arbitrary tenant."""
from alembic import op
import sqlalchemy as sa

revision = '20260876_dmarc_tenant_boundary'
down_revision = '20260875_evaluation_tenant_integrity'
branch_labels = None
depends_on = None


def upgrade():
    # Keep migration history independent of future runtime schema changes.
    bind = op.get_bind()
    if not sa.inspect(bind).has_table('dmarc_reports'):
        op.create_table('dmarc_reports',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('tenant_id', sa.Text(), nullable=True),
            sa.Column('org_name', sa.Text()), sa.Column('domain', sa.Text()),
            sa.Column('begin', sa.BigInteger()), sa.Column('end', sa.BigInteger()),
            sa.Column('report_id', sa.Text()))
    if not sa.inspect(bind).has_table('dmarc_records'):
        op.create_table('dmarc_records',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('report_fk', sa.Integer(), sa.ForeignKey('dmarc_reports.id')),
            sa.Column('source_ip', sa.Text()), sa.Column('count', sa.Integer()),
            sa.Column('spf', sa.Text()), sa.Column('dkim', sa.Text()),
            sa.Column('disposition', sa.Text()))
    if 'tenant_id' not in {c['name'] for c in sa.inspect(bind).get_columns('dmarc_reports')}:
        op.add_column('dmarc_reports', sa.Column('tenant_id', sa.Text(), nullable=True))
    op.create_index('ix_dmarc_report_tenant_end', 'dmarc_reports', ['tenant_id', 'end'])


def downgrade():
    # Preserve ownership columns and reports; removing them would reopen an
    # isolation boundary and destroy evidence attribution.
    op.drop_index('ix_dmarc_report_tenant_end', table_name='dmarc_reports')
