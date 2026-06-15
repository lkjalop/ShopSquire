"""Authorization control-plane tables — the four tables the autonomy decks mark
"not optional" for a bounded-autonomous system.

Revision ID: 20260614_authz_cp
Revises: 20260608_perf_rls
Create Date: 2026-06-14

Why: the Authorization Engine (src/app/security/authorization_engine.py) is the
Tier-1 control. For its decisions to be provable + recoverable, every gate
evaluation needs a durable home and every non-execute outcome needs a tracked,
terminal resolution path. These four tables provide exactly that:

  1. policy_evaluation_log — one row per authorize() call (the audit of the gate itself)
  2. exception_queue       — every non-execute outcome, guaranteed a terminal status
  3. retry_tracking        — idempotency + retry bookkeeping (no double-execution)
  4. ai_interaction_log    — what the AI PROPOSED vs. what the engine DISPOSED (provenance)

All additive + guarded by _has_table so re-running is a no-op and no existing
table/column is touched. The engine writes to these best-effort, so the platform
runs identically whether or not this migration has been applied yet.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260614_authz_cp"
down_revision = "20260608_perf_rls"
branch_labels = None
depends_on = None


def _has_table(name: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return bool(insp.has_table(name))


def upgrade() -> None:
    # ── 1. policy_evaluation_log ─────────────────────────────────────────────
    if not _has_table("policy_evaluation_log"):
        op.create_table(
            "policy_evaluation_log",
            sa.Column("id", sa.Text(), primary_key=True),
            sa.Column("trace_id", sa.Text(), nullable=True),
            sa.Column("policy_version", sa.Text(), nullable=False),
            sa.Column("action", sa.Text(), nullable=False),
            sa.Column("requester", sa.Text(), nullable=False),
            sa.Column("decision", sa.Text(), nullable=False),
            sa.Column("terminal_outcome", sa.Text(), nullable=False),
            sa.Column("mode", sa.Text(), nullable=False, server_default="shadow"),
            sa.Column("enforced", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("reason", sa.Text(), nullable=True),
            sa.Column("value_usd", sa.Float(), nullable=True, server_default="0"),
            sa.Column("confidence", sa.Float(), nullable=True, server_default="0"),
            sa.Column("guardrails_json", sa.Text(), nullable=True),
            sa.Column("compromise_json", sa.Text(), nullable=True),
            sa.Column("residual", sa.Text(), nullable=True),
            sa.Column("created_at", sa.Text(), nullable=False),
        )
        op.create_index("ix_policy_evaluation_log_action", "policy_evaluation_log", ["action"])
        op.create_index("ix_policy_evaluation_log_decision", "policy_evaluation_log", ["decision"])
        op.create_index("ix_policy_evaluation_log_trace_id", "policy_evaluation_log", ["trace_id"])
        op.create_index("ix_policy_evaluation_log_created_at", "policy_evaluation_log", ["created_at"])

    # ── 2. exception_queue ───────────────────────────────────────────────────
    if not _has_table("exception_queue"):
        op.create_table(
            "exception_queue",
            sa.Column("id", sa.Text(), primary_key=True),
            sa.Column("trace_id", sa.Text(), nullable=True),
            sa.Column("action", sa.Text(), nullable=False),
            sa.Column("requester", sa.Text(), nullable=False),
            sa.Column("terminal_outcome", sa.Text(), nullable=False),
            sa.Column("reason", sa.Text(), nullable=True),
            sa.Column("subject_id", sa.Text(), nullable=True),
            sa.Column("value_usd", sa.Float(), nullable=True, server_default="0"),
            sa.Column("residual", sa.Text(), nullable=True),
            sa.Column("status", sa.Text(), nullable=False, server_default="open"),
            sa.Column("resolved_outcome", sa.Text(), nullable=True),
            sa.Column("created_at", sa.Text(), nullable=False),
            sa.Column("resolved_at", sa.Text(), nullable=True),
        )
        op.create_index("ix_exception_queue_status", "exception_queue", ["status"])
        op.create_index("ix_exception_queue_action", "exception_queue", ["action"])
        op.create_index("ix_exception_queue_subject_id", "exception_queue", ["subject_id"])
        op.create_index("ix_exception_queue_created_at", "exception_queue", ["created_at"])

    # ── 3. retry_tracking ────────────────────────────────────────────────────
    if not _has_table("retry_tracking"):
        op.create_table(
            "retry_tracking",
            sa.Column("idempotency_key", sa.Text(), primary_key=True),
            sa.Column("action", sa.Text(), nullable=False),
            sa.Column("requester", sa.Text(), nullable=True),
            sa.Column("decision", sa.Text(), nullable=True),
            sa.Column("terminal_outcome", sa.Text(), nullable=True),
            sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("last_status", sa.Text(), nullable=True),
            sa.Column("first_seen_at", sa.Text(), nullable=False),
            sa.Column("last_attempt_at", sa.Text(), nullable=True),
            sa.Column("next_retry_at", sa.Text(), nullable=True),
        )
        op.create_index("ix_retry_tracking_action", "retry_tracking", ["action"])
        op.create_index("ix_retry_tracking_next_retry_at", "retry_tracking", ["next_retry_at"])

    # ── 4. ai_interaction_log ────────────────────────────────────────────────
    if not _has_table("ai_interaction_log"):
        op.create_table(
            "ai_interaction_log",
            sa.Column("id", sa.Text(), primary_key=True),
            sa.Column("trace_id", sa.Text(), nullable=True),
            sa.Column("interaction_type", sa.Text(), nullable=False),
            sa.Column("actor", sa.Text(), nullable=True),
            sa.Column("action", sa.Text(), nullable=True),
            sa.Column("proposed_json", sa.Text(), nullable=True),
            sa.Column("disposed_json", sa.Text(), nullable=True),
            sa.Column("subject_id", sa.Text(), nullable=True),
            sa.Column("created_at", sa.Text(), nullable=False),
        )
        op.create_index("ix_ai_interaction_log_interaction_type", "ai_interaction_log", ["interaction_type"])
        op.create_index("ix_ai_interaction_log_trace_id", "ai_interaction_log", ["trace_id"])
        op.create_index("ix_ai_interaction_log_created_at", "ai_interaction_log", ["created_at"])


def downgrade() -> None:
    for tbl in [
        "ai_interaction_log",
        "retry_tracking",
        "exception_queue",
        "policy_evaluation_log",
    ]:
        op.execute(f"DROP TABLE IF EXISTS {tbl}")
