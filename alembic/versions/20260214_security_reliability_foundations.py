"""security + reliability foundations (pii fields, action dlq, audit chain)

Revision ID: f4a8c2d6e0b1
Revises: e2f4a6b8c0d1
Create Date: 2026-02-14 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "f4a8c2d6e0b1"
down_revision = "e2f4a6b8c0d1"
branch_labels = None
depends_on = None


def _ensure_col(table: str, col: str, coltype: sa.types.TypeEngine) -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = {c.get("name") for c in insp.get_columns(table)} if insp.has_table(table) else set()
    if col not in cols:
        op.add_column(table, sa.Column(col, coltype, nullable=True))


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if insp.has_table("orders"):
        _ensure_col("orders", "guest_email_hash", sa.Text())
        _ensure_col("orders", "guest_email_encrypted", sa.Text())

    if insp.has_table("cases"):
        _ensure_col("cases", "guest_email_hash", sa.Text())
        _ensure_col("cases", "guest_email_encrypted", sa.Text())

    if insp.has_table("customers"):
        _ensure_col("customers", "email_hash", sa.Text())
        _ensure_col("customers", "email_encrypted", sa.Text())
        _ensure_col("customers", "phone_encrypted", sa.Text())

    if not insp.has_table("playbook_action_executions"):
        op.create_table(
            "playbook_action_executions",
            sa.Column("id", sa.Text(), primary_key=True),
            sa.Column("run_id", sa.Text(), nullable=False),
            sa.Column("step_index", sa.Integer(), nullable=False),
            sa.Column("action_type", sa.Text(), nullable=False),
            sa.Column("idempotency_key", sa.Text(), nullable=False),
            sa.Column("attempt", sa.Integer(), nullable=False),
            sa.Column("status", sa.Text(), nullable=False),
            sa.Column("result_json", sa.Text(), nullable=True),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("created_at", sa.Text(), nullable=False),
        )
    if not insp.has_table("playbook_action_dlq"):
        op.create_table(
            "playbook_action_dlq",
            sa.Column("id", sa.Text(), primary_key=True),
            sa.Column("run_id", sa.Text(), nullable=False),
            sa.Column("step_index", sa.Integer(), nullable=False),
            sa.Column("action_type", sa.Text(), nullable=False),
            sa.Column("idempotency_key", sa.Text(), nullable=False),
            sa.Column("payload_json", sa.Text(), nullable=False),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column("created_at", sa.Text(), nullable=False),
        )
    try:
        op.create_index("ix_playbook_action_exec_idem", "playbook_action_executions", ["idempotency_key"], unique=False)
    except Exception:
        pass
    try:
        op.create_index("ix_playbook_action_dlq_run", "playbook_action_dlq", ["run_id", "step_index"], unique=False)
    except Exception:
        pass

    if not insp.has_table("audit_log_chain"):
        op.create_table(
            "audit_log_chain",
            sa.Column("id", sa.Text(), primary_key=True),
            sa.Column("source_type", sa.Text(), nullable=False),
            sa.Column("source_id", sa.Text(), nullable=True),
            sa.Column("payload_hash", sa.Text(), nullable=False),
            sa.Column("prev_hash", sa.Text(), nullable=True),
            sa.Column("merkle_root", sa.Text(), nullable=False),
            sa.Column("created_at", sa.Text(), nullable=False),
        )
    try:
        op.create_index("ix_audit_log_chain_created", "audit_log_chain", ["created_at"], unique=False)
    except Exception:
        pass


def downgrade() -> None:
    try:
        op.drop_index("ix_audit_log_chain_created", table_name="audit_log_chain")
    except Exception:
        pass
    try:
        op.drop_table("audit_log_chain")
    except Exception:
        pass
    try:
        op.drop_index("ix_playbook_action_dlq_run", table_name="playbook_action_dlq")
    except Exception:
        pass
    try:
        op.drop_index("ix_playbook_action_exec_idem", table_name="playbook_action_executions")
    except Exception:
        pass
    try:
        op.drop_table("playbook_action_dlq")
    except Exception:
        pass
    try:
        op.drop_table("playbook_action_executions")
    except Exception:
        pass
