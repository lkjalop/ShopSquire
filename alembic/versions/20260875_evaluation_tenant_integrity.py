"""Preserve legacy evaluation rows without treating them as measured release evidence."""
from alembic import op
import sqlalchemy as sa

revision = '20260875_evaluation_tenant_integrity'
down_revision = '20260874_post_purchase_satisfaction'
branch_labels = None
depends_on = None


def upgrade():
    # Older PostgreSQL security_events tables never received runtime-only
    # ownership columns. Keep legacy rows unassigned instead of inventing a tenant.
    for table in ('security_events', 'incidents', 'decision_logs'):
        columns = {column['name'] for column in sa.inspect(op.get_bind()).get_columns(table)}
        if 'tenant_id' not in columns:
            op.add_column(table, sa.Column('tenant_id', sa.Text(), nullable=True))
    op.add_column('ragas_eval_results', sa.Column('tenant_id', sa.Text(), nullable=True))
    op.add_column('ragas_eval_results', sa.Column('evaluation_status', sa.Text(), nullable=False, server_default='legacy_unverified'))
    op.add_column('ragas_eval_results', sa.Column('metadata_json', sa.Text(), nullable=True))
    op.add_column('ragas_baseline', sa.Column('tenant_id', sa.Text(), nullable=True))
    op.add_column('ragas_baseline', sa.Column('metadata_json', sa.Text(), nullable=True))
    op.create_index('ix_ragas_tenant_created', 'ragas_eval_results', ['tenant_id', 'created_at'])
    op.execute('''UPDATE ragas_eval_results SET tenant_id =
        (SELECT tenant_id FROM decision_logs WHERE decision_logs.id = ragas_eval_results.decision_log_id)
        WHERE tenant_id IS NULL''')
    if op.get_bind().dialect.name == 'postgresql':
        for table in ('security_events', 'incidents', 'decision_logs'):
            op.execute(f'ALTER TABLE {table} ENABLE ROW LEVEL SECURITY')
            op.execute(f'DROP POLICY IF EXISTS tenant_isolation_{table} ON {table}')
            op.execute(f'''CREATE POLICY tenant_isolation_{table} ON {table}
                USING (tenant_id = NULLIF(current_setting('app.current_tenant', true), ''))
                WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant', true), ''))''')


def downgrade():
    # Do not silently restore permissive tenant policies on rollback.
    op.drop_index('ix_ragas_tenant_created', table_name='ragas_eval_results')
    for table, columns in (('ragas_eval_results', ('metadata_json', 'evaluation_status', 'tenant_id')),
                           ('ragas_baseline', ('metadata_json', 'tenant_id'))):
        for column in columns:
            op.drop_column(table, column)
