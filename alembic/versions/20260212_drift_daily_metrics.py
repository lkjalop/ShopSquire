"""drift daily metrics table

Revision ID: d1e2f3a4b5c6
Revises: c7d8e9f0a2b3
Create Date: 2026-02-12 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "d1e2f3a4b5c6"
down_revision = "c7d8e9f0a2b3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if insp.has_table("drift_daily_metrics"):
        return

    op.create_table(
        "drift_daily_metrics",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("tenant_id", sa.Text(), nullable=True),
        sa.Column("day", sa.Text(), nullable=False),
        sa.Column("domain", sa.Text(), nullable=False),
        sa.Column("metric_key", sa.Text(), nullable=False),
        sa.Column("metric_value", sa.Float(), nullable=False),
        sa.Column("labels_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("labels_hash", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=True, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.Text(), nullable=True, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    try:
        op.create_index(
            "ux_drift_daily_metrics_key",
            "drift_daily_metrics",
            ["tenant_id", "day", "domain", "metric_key", "labels_hash"],
            unique=True,
        )
    except Exception:
        pass
    try:
        op.create_index("ix_drift_daily_metrics_day", "drift_daily_metrics", ["day", "domain"])
    except Exception:
        pass


def downgrade() -> None:
    # Non-destructive
    pass

