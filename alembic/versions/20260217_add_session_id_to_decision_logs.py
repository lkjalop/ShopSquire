"""add session_id to decision_logs

Revision ID: 20260217_session_id
Revises: 20260216_merge_heads_product_embeddings_and_timescale
Create Date: 2026-02-17 00:00:00.000000

Adds a nullable ``session_id TEXT`` column to ``decision_logs`` so that
decisions originating from the same conversational session can be grouped
and retrieved via ``GET /api/v1/decisions/session/{session_id}``.
An index is created to make the lookup efficient.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260217_session_id"
down_revision = "20260216_merge_heads_product_embeddings_and_timescale"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("decision_logs") as batch_op:
        batch_op.add_column(sa.Column("session_id", sa.Text(), nullable=True))

    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_decision_logs_session_id ON decision_logs (session_id)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_decision_logs_session_id")
    with op.batch_alter_table("decision_logs") as batch_op:
        batch_op.drop_column("session_id")
