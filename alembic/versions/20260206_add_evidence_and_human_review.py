"""add evidence_bundles and human_review_tasks tables

Revision ID: f3c206a0e6a1
Revises: 20260128_add_tenant_id
Create Date: 2026-02-06 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "f3c206a0e6a1"
down_revision = '20260128_add_tenant_id'
branch_labels = None
depends_on = None


def _has_table(name: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return bool(insp.has_table(name))


def upgrade():
    if not _has_table("evidence_bundles"):
        op.create_table(
            'evidence_bundles',
            sa.Column('id', sa.Text(), primary_key=True),
            sa.Column('case_id', sa.Text(), nullable=False),
            sa.Column('bundle_json', sa.Text(), nullable=False),
            sa.Column('created_at', sa.Text(), nullable=True),
        )

    if not _has_table("human_review_tasks"):
        op.create_table(
            'human_review_tasks',
            sa.Column('id', sa.Text(), primary_key=True),
            sa.Column('case_id', sa.Text(), nullable=False),
            sa.Column('decision_id', sa.Text(), nullable=True),
            sa.Column('ticket_id', sa.Text(), nullable=True),
            sa.Column('status', sa.Text(), nullable=False, server_default='pending'),
            sa.Column('reviewer_id', sa.Text(), nullable=True),
            sa.Column('rationale', sa.Text(), nullable=True),
            sa.Column('created_at', sa.Text(), nullable=True),
            sa.Column('updated_at', sa.Text(), nullable=True),
        )


def downgrade():
    if _has_table("human_review_tasks"):
        op.drop_table('human_review_tasks')
    if _has_table("evidence_bundles"):
        op.drop_table('evidence_bundles')
