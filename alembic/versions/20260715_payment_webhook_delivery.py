"""Durable payment webhook inbox and side-effect outbox."""
from alembic import op
import sqlalchemy as sa

revision = "20260715_payment_webhook_delivery"
down_revision = "20260714_stripe_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    # Alembic creates version_num as VARCHAR(32), but this revision identifier is
    # 33 characters. Widen it before Alembic records this revision; otherwise a
    # clean PostgreSQL upgrade fails after all business DDL has succeeded.
    if "postgres" in str(getattr(bind.dialect, "name", "")).lower():
        op.execute("ALTER TABLE alembic_version ALTER COLUMN version_num TYPE VARCHAR(64)")
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "stripe_events" not in tables:
        op.create_table(
            "stripe_events",
            sa.Column("event_id", sa.Text(), primary_key=True),
            sa.Column("type", sa.Text()),
            sa.Column("processed_at", sa.Text()),
        )
    existing = {c["name"] for c in sa.inspect(bind).get_columns("stripe_events")}
    additions = {
        "payload": sa.Column("payload", sa.Text()),
        "state": sa.Column("state", sa.Text(), nullable=False, server_default="pending"),
        "attempts": sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        "claim_token": sa.Column("claim_token", sa.Text()),
        "lease_expires_at": sa.Column("lease_expires_at", sa.Float()),
        "last_error": sa.Column("last_error", sa.Text()),
        "created_at": sa.Column("created_at", sa.Text(), server_default=sa.text("CURRENT_TIMESTAMP")),
        "updated_at": sa.Column("updated_at", sa.Text(), server_default=sa.text("CURRENT_TIMESTAMP")),
    }
    for name, column in additions.items():
        if name not in existing:
            op.add_column("stripe_events", column)
    op.execute("UPDATE stripe_events SET state='processed' WHERE state IS NULL")

    refund_columns = {c["name"] for c in sa.inspect(bind).get_columns("refund_executions")}
    if "claim_token" not in refund_columns:
        op.add_column("refund_executions", sa.Column("claim_token", sa.Text()))
    if "lease_expires_at" not in refund_columns:
        op.add_column("refund_executions", sa.Column("lease_expires_at", sa.Float()))

    if "payment_side_effect_jobs" not in tables:
        op.create_table(
            "payment_side_effect_jobs",
            sa.Column("id", sa.Text(), primary_key=True),
            sa.Column("event_id", sa.Text(), nullable=False),
            sa.Column("job_type", sa.Text(), nullable=False),
            sa.Column("payload", sa.Text(), nullable=False),
            sa.Column("state", sa.Text(), nullable=False, server_default="pending"),
            sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("claim_token", sa.Text()),
            sa.Column("lease_expires_at", sa.Float()),
            sa.Column("last_error", sa.Text()),
            sa.Column("created_at", sa.Text(), server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("updated_at", sa.Text(), server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("processed_at", sa.Text()),
            sa.UniqueConstraint("event_id", "job_type", name="uq_payment_side_effect_event_type"),
        )
        op.create_index("ix_payment_side_effect_jobs_state", "payment_side_effect_jobs",
                        ["state", "lease_expires_at"])


def downgrade() -> None:
    bind = op.get_bind()
    if "payment_side_effect_jobs" in set(sa.inspect(bind).get_table_names()):
        op.drop_table("payment_side_effect_jobs")
