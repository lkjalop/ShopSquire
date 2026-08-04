"""Bind cache generations to exact subjects and sealed rebuild recipes.

Revision ID: 20260850_temporal_cache_binding
Revises: 20260849_temporal_cache_lifecycle
"""

from alembic import op
import sqlalchemy as sa


revision = "20260850_temporal_cache_binding"
down_revision = "20260849_temporal_cache_lifecycle"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "temporal_cache_binding",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("cache_key", sa.Text(), nullable=False),
        sa.Column("namespace", sa.Text(), nullable=False),
        sa.Column("subject_type", sa.Text(), nullable=False),
        sa.Column("subject_id", sa.Text(), nullable=False),
        sa.Column("session_epoch", sa.Text(), nullable=False),
        sa.Column("rebuild_payload_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.UniqueConstraint("tenant_id", "cache_key", name="uq_temporal_cache_binding"),
        sa.CheckConstraint(
            "subject_type IN ('case','shared')", name="ck_temporal_cache_binding_subject_type"
        ),
    )
    op.create_index(
        "ix_temporal_cache_binding_subject",
        "temporal_cache_binding",
        ["tenant_id", "subject_type", "subject_id", "session_epoch"],
    )


def downgrade() -> None:
    op.drop_index("ix_temporal_cache_binding_subject", table_name="temporal_cache_binding")
    op.drop_table("temporal_cache_binding")
