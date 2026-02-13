"""add tenant_id to decision_logs

Revision ID: 20260128_add_tenant_id
Revises: 20260128_create_rule_definitions
Create Date: 2026-01-28 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '20260128_add_tenant_id'
down_revision = '20260128_create_rule_definitions'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    insp = sa.inspect(conn)
    cols = {c["name"] for c in insp.get_columns("decision_logs")}
    if "tenant_id" in cols:
        return
    conn.execute(sa.text("ALTER TABLE decision_logs ADD COLUMN tenant_id TEXT"))


def downgrade():
    conn = op.get_bind()
    dialect = str(getattr(getattr(conn, "dialect", None), "name", "") or "").lower()
    if dialect == "sqlite":
        return
    insp = sa.inspect(conn)
    cols = {c["name"] for c in insp.get_columns("decision_logs")}
    if "tenant_id" not in cols:
        return
    conn.execute(sa.text("ALTER TABLE decision_logs DROP COLUMN tenant_id"))
