"""Repair ownership columns and enforce policy on already-upgraded databases."""
from alembic import op
import sqlalchemy as sa

revision = '20260893_security_tenant_policy'
down_revision = '20260892_buyer_supplier_selection'
branch_labels = None
depends_on = None


def upgrade():
    # Freeze this repair locally: later runtime metadata must not rewrite history.
    for table in ('security_events', 'incidents', 'decision_logs'):
        columns = {column['name'] for column in sa.inspect(op.get_bind()).get_columns(table)}
        if 'tenant_id' not in columns:
            op.add_column(table, sa.Column('tenant_id', sa.Text(), nullable=True))
        if op.get_bind().dialect.name == 'postgresql':
            op.execute(f'ALTER TABLE {table} ENABLE ROW LEVEL SECURITY')
            op.execute(f'DROP POLICY IF EXISTS tenant_isolation_{table} ON {table}')
            op.execute(f'''CREATE POLICY tenant_isolation_{table} ON {table}
                USING (tenant_id = NULLIF(current_setting('app.current_tenant', true), ''))
                WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant', true), ''))''')


def downgrade():
    # Retain ownership and the restrictive policy; reopening access is not rollback.
    pass
