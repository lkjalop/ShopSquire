"""Add canonical tenant-scoped escalation ownership.

Revision ID: 20260855_case_escalation
Revises: 20260854_exception_queue
"""

from alembic import op
import sqlalchemy as sa


revision = "20260855_case_escalation"
down_revision = "20260854_exception_queue"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "case_escalation",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("domain", sa.Text(), nullable=False),
        sa.Column("party_ref", sa.Text()),
        sa.Column("case_id", sa.Text(), nullable=False),
        sa.Column("order_line_id", sa.Text()),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("priority", sa.Text(), nullable=False),
        sa.Column("reason_code", sa.Text(), nullable=False),
        sa.Column("trigger_observation_ref", sa.Text()),
        sa.Column("trace_id", sa.Text()),
        sa.Column("evidence_refs_json", sa.Text(), nullable=False),
        sa.Column("policy_version", sa.Text(), nullable=False),
        sa.Column("required_response_at", sa.Text()),
        sa.Column("assigned_operator_id", sa.Text()),
        sa.Column("ticket_id", sa.Text()),
        sa.Column("final_disposition", sa.Text()),
        sa.Column("resulting_amendment_id", sa.String(64)),
        sa.Column("dedupe_key", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.UniqueConstraint("tenant_id", "dedupe_key", name="uq_case_escalation_dedupe"),
        sa.CheckConstraint(
            "state IN ('requested','assigned','operator_joined','responded','unavailable','resolved')",
            name="ck_case_escalation_state",
        ),
    )
    op.create_index(
        "ix_case_escalation_queue", "case_escalation",
        ["tenant_id", "state", "priority", "created_at"],
    )
    op.create_index(
        "ix_case_escalation_case", "case_escalation",
        ["tenant_id", "case_id", "order_line_id"],
    )
    op.create_table(
        "case_escalation_event",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("escalation_id", sa.Text(), sa.ForeignKey("case_escalation.id"), nullable=False),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("from_state", sa.Text()),
        sa.Column("to_state", sa.Text(), nullable=False),
        sa.Column("actor_type", sa.Text(), nullable=False),
        sa.Column("actor_id", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text()),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("occurred_at", sa.Text(), nullable=False),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_case_escalation_event_idem"),
    )
    op.create_index(
        "ix_case_escalation_event_timeline", "case_escalation_event",
        ["tenant_id", "escalation_id", "occurred_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_case_escalation_event_timeline", table_name="case_escalation_event")
    op.drop_table("case_escalation_event")
    op.drop_index("ix_case_escalation_case", table_name="case_escalation")
    op.drop_index("ix_case_escalation_queue", table_name="case_escalation")
    op.drop_table("case_escalation")
