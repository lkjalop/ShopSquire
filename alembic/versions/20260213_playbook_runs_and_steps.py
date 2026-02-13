"""create playbook run execution tables

Revision ID: e2f4a6b8c0d1
Revises: d1e2f3a4b5c6
Create Date: 2026-02-13 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "e2f4a6b8c0d1"
down_revision = "d1e2f3a4b5c6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if not insp.has_table("playbook_runs"):
        op.create_table(
            "playbook_runs",
            sa.Column("id", sa.Text(), primary_key=True),
            sa.Column("trace_id", sa.Text(), nullable=True),
            sa.Column("decision_id", sa.Text(), nullable=True),
            sa.Column("tenant_id", sa.Text(), nullable=True),
            sa.Column("playbook_id", sa.Text(), nullable=False),
            sa.Column("playbook_version", sa.Text(), nullable=False),
            sa.Column("owner", sa.Text(), nullable=True),
            sa.Column("status", sa.Text(), nullable=False),
            sa.Column("outcome", sa.Text(), nullable=True),
            sa.Column("posthoc_outcome_id", sa.Text(), nullable=True),
            sa.Column("metadata_json", sa.Text(), nullable=True),
            sa.Column("started_at", sa.Text(), nullable=False),
            sa.Column("ended_at", sa.Text(), nullable=True),
        )
    if not insp.has_table("playbook_run_steps"):
        op.create_table(
            "playbook_run_steps",
            sa.Column("id", sa.Text(), primary_key=True),
            sa.Column("run_id", sa.Text(), nullable=False),
            sa.Column("step_index", sa.Integer(), nullable=False),
            sa.Column("event_type", sa.Text(), nullable=False),
            sa.Column("status", sa.Text(), nullable=False),
            sa.Column("evidence_json", sa.Text(), nullable=True),
            sa.Column("created_at", sa.Text(), nullable=False),
        )

    try:
        op.create_index("ix_playbook_runs_trace", "playbook_runs", ["trace_id"], unique=False)
    except Exception:
        pass
    try:
        op.create_index("ix_playbook_runs_playbook", "playbook_runs", ["playbook_id", "playbook_version"], unique=False)
    except Exception:
        pass
    try:
        op.create_index("ix_playbook_run_steps_run", "playbook_run_steps", ["run_id", "step_index"], unique=False)
    except Exception:
        pass


def downgrade() -> None:
    try:
        op.drop_index("ix_playbook_run_steps_run", table_name="playbook_run_steps")
    except Exception:
        pass
    try:
        op.drop_index("ix_playbook_runs_playbook", table_name="playbook_runs")
    except Exception:
        pass
    try:
        op.drop_index("ix_playbook_runs_trace", table_name="playbook_runs")
    except Exception:
        pass
    try:
        op.drop_table("playbook_run_steps")
    except Exception:
        pass
    try:
        op.drop_table("playbook_runs")
    except Exception:
        pass
