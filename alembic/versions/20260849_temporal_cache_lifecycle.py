"""Add durable CacheRAG generation and rebuild lifecycle.

Revision ID: 20260849_temporal_cache_lifecycle
Revises: 20260848_disruption_observation
"""

from alembic import op
import sqlalchemy as sa


revision = "20260849_temporal_cache_lifecycle"
down_revision = "20260848_disruption_observation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "temporal_cache_entry",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("cache_key", sa.Text(), nullable=False),
        sa.Column("namespace", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("current_generation", sa.Integer()),
        sa.Column("pending_generation", sa.Integer()),
        sa.Column("last_error", sa.Text()),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.UniqueConstraint("tenant_id", "cache_key", name="uq_temporal_cache_entry"),
        sa.CheckConstraint(
            "status IN ('fresh','stale','invalidated','rebuild_queued','rebuilding',"
            "'rebuilt','degraded','superseded','failed')",
            name="ck_temporal_cache_entry_status",
        ),
    )
    op.create_index(
        "ix_temporal_cache_entry_status",
        "temporal_cache_entry",
        ["tenant_id", "status", "updated_at"],
    )
    op.create_table(
        "temporal_cache_generation",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("entry_id", sa.Text(), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("storage_key", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.Text()),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("published_at", sa.Text()),
        sa.Column("superseded_at", sa.Text()),
        sa.ForeignKeyConstraint(["entry_id"], ["temporal_cache_entry.id"]),
        sa.UniqueConstraint("entry_id", "generation", name="uq_temporal_cache_generation"),
        sa.CheckConstraint(
            "status IN ('fresh','rebuilding','rebuilt','superseded','failed')",
            name="ck_temporal_cache_generation_status",
        ),
    )
    op.create_table(
        "temporal_cache_rebuild_job",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("entry_id", sa.Text(), nullable=False),
        sa.Column("cache_key", sa.Text(), nullable=False),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("source_type", sa.Text(), nullable=False),
        sa.Column("source_id", sa.Text(), nullable=False),
        sa.Column("source_version", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("dispatch_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("dispatched_at", sa.Text()),
        sa.Column("started_at", sa.Text()),
        sa.Column("finished_at", sa.Text()),
        sa.Column("last_error", sa.Text()),
        sa.ForeignKeyConstraint(["entry_id"], ["temporal_cache_entry.id"]),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_temporal_cache_rebuild_idem"),
        sa.CheckConstraint(
            "status IN ('queued','running','succeeded','degraded','failed')",
            name="ck_temporal_cache_rebuild_status",
        ),
    )
    op.create_index(
        "ix_temporal_cache_rebuild_due",
        "temporal_cache_rebuild_job",
        ["tenant_id", "status", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_temporal_cache_rebuild_due", table_name="temporal_cache_rebuild_job")
    op.drop_table("temporal_cache_rebuild_job")
    op.drop_table("temporal_cache_generation")
    op.drop_index("ix_temporal_cache_entry_status", table_name="temporal_cache_entry")
    op.drop_table("temporal_cache_entry")
