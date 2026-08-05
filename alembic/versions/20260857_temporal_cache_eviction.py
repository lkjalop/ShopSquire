"""Make failed physical cache eviction durable and observable.

Revision ID: 20260857_cache_eviction
Revises: 20260856_escalation_projection
"""

from alembic import op
import sqlalchemy as sa


revision = "20260857_cache_eviction"
down_revision = "20260856_escalation_projection"
branch_labels = None
depends_on = None


_OLD_STATUSES = (
    "'fresh','stale','invalidated','rebuild_queued','rebuilding','rebuilt',"
    "'degraded','superseded','failed'"
)
_NEW_STATUSES = (
    "'fresh','stale','invalidated','rebuild_queued','rebuilding','rebuilt',"
    "'degraded','superseded','superseded_eviction_pending','failed'"
)


def upgrade() -> None:
    with op.batch_alter_table("temporal_cache_entry") as batch:
        batch.drop_constraint("ck_temporal_cache_entry_status", type_="check")
        batch.create_check_constraint(
            "ck_temporal_cache_entry_status", f"status IN ({_NEW_STATUSES})"
        )
    op.create_table(
        "temporal_cache_eviction_job",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("entry_id", sa.Text(), nullable=False),
        sa.Column("cache_key", sa.Text(), nullable=False),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("dispatch_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("dispatched_at", sa.Text()),
        sa.Column("started_at", sa.Text()),
        sa.Column("finished_at", sa.Text()),
        sa.Column("last_error", sa.Text()),
        sa.ForeignKeyConstraint(["entry_id"], ["temporal_cache_entry.id"]),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_temporal_cache_eviction_idem"),
        sa.CheckConstraint(
            "status IN ('queued','running','succeeded','degraded','failed')",
            name="ck_temporal_cache_eviction_status",
        ),
    )
    op.create_index(
        "ix_temporal_cache_eviction_due",
        "temporal_cache_eviction_job",
        ["tenant_id", "status", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_temporal_cache_eviction_due", table_name="temporal_cache_eviction_job")
    op.drop_table("temporal_cache_eviction_job")
    with op.batch_alter_table("temporal_cache_entry") as batch:
        batch.drop_constraint("ck_temporal_cache_entry_status", type_="check")
        batch.create_check_constraint(
            "ck_temporal_cache_entry_status", f"status IN ({_OLD_STATUSES})"
        )
