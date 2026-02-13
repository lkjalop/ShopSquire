"""create rule_definitions table and seed baseline rules

Revision ID: 20260128_create_rule_definitions
Revises: e97e71ba6492
Create Date: 2026-01-28 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision = '20260128_create_rule_definitions'
down_revision = 'e97e71ba6492'
branch_labels = None
depends_on = None


def _dialect_name() -> str:
    bind = op.get_bind()
    return str(getattr(getattr(bind, "dialect", None), "name", "") or "").lower()


def _has_table(name: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return bool(insp.has_table(name))


def upgrade():
    conn = op.get_bind()
    dialect = _dialect_name()
    active_default = sa.text("true") if "postgres" in dialect else sa.text("1")

    if not _has_table("rule_definitions"):
        op.create_table(
            'rule_definitions',
            sa.Column('id', sa.Text(), primary_key=True),
            sa.Column('tenant_id', sa.Text(), nullable=True),
            sa.Column('title', sa.Text(), nullable=False),
            sa.Column('pattern', sa.Text(), nullable=True),
            sa.Column('expression', sa.Text(), nullable=True),
            sa.Column('priority', sa.Integer(), nullable=False, server_default='100'),
            sa.Column('active', sa.Boolean(), nullable=False, server_default=active_default),
            sa.Column('created_by', sa.Text(), nullable=True),
            sa.Column('version', sa.Text(), nullable=True),
            sa.Column('effective_from', sa.Text(), nullable=True),
            sa.Column('effective_to', sa.Text(), nullable=True),
            sa.Column('created_at', sa.Text(), nullable=True),
        )

    # Seed baseline rules (simple regex patterns) - safe to run multiple times
    if "postgres" in dialect:
        conn.execute(text(
            "INSERT INTO rule_definitions (id, tenant_id, title, pattern, priority, active, created_by, version, created_at) "
            "VALUES ('r_prod_search', NULL, 'product_search', 'show\\s+me|find|search\\s+for|looking\\s+for|i\\s+need|i\\s+want', 10, true, 'system', 'v1', CURRENT_TIMESTAMP) "
            "ON CONFLICT (id) DO NOTHING"
        ))
        conn.execute(text(
            "INSERT INTO rule_definitions (id, tenant_id, title, pattern, priority, active, created_by, version, created_at) "
            "VALUES ('r_price_check', NULL, 'price_check', 'how\\s+much|price\\s+of|cost|pricing', 10, true, 'system', 'v1', CURRENT_TIMESTAMP) "
            "ON CONFLICT (id) DO NOTHING"
        ))
        conn.execute(text(
            "INSERT INTO rule_definitions (id, tenant_id, title, pattern, priority, active, created_by, version, created_at) "
            "VALUES ('r_comparison', NULL, 'comparison', 'compare|vs|versus|difference\\s+between|which\\s+is\\s+better', 20, true, 'system', 'v1', CURRENT_TIMESTAMP) "
            "ON CONFLICT (id) DO NOTHING"
        ))
        return

    # SQLite fallback
    conn.execute(text(
        "INSERT OR IGNORE INTO rule_definitions (id, tenant_id, title, pattern, priority, active, created_by, version, created_at) "
        "VALUES ('r_prod_search', NULL, 'product_search', 'show\\s+me|find|search\\s+for|looking\\s+for|i\\s+need|i\\s+want', 10, 1, 'system', 'v1', CURRENT_TIMESTAMP)"
    ))
    conn.execute(text(
        "INSERT OR IGNORE INTO rule_definitions (id, tenant_id, title, pattern, priority, active, created_by, version, created_at) "
        "VALUES ('r_price_check', NULL, 'price_check', 'how\\s+much|price\\s+of|cost|pricing', 10, 1, 'system', 'v1', CURRENT_TIMESTAMP)"
    ))
    conn.execute(text(
        "INSERT OR IGNORE INTO rule_definitions (id, tenant_id, title, pattern, priority, active, created_by, version, created_at) "
        "VALUES ('r_comparison', NULL, 'comparison', 'compare|vs|versus|difference\\s+between|which\\s+is\\s+better', 20, 1, 'system', 'v1', CURRENT_TIMESTAMP)"
    ))


def downgrade():
    if _has_table("rule_definitions"):
        op.drop_table('rule_definitions')
