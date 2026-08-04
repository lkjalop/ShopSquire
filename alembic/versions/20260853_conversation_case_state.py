"""Add canonical conversation case state and append-only amendments.

Revision ID: 20260853_conversation_case
Revises: 20260852_procurement_runtime
"""

from alembic import op
import sqlalchemy as sa


revision = "20260853_conversation_case"
down_revision = "20260852_procurement_runtime"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "conversation_case_state",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("case_id", sa.Text(), nullable=False),
        sa.Column("session_epoch", sa.Text(), nullable=False),
        sa.Column("subject_ref", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("state_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.UniqueConstraint("tenant_id", "case_id", "session_epoch", name="uq_conversation_case_epoch"),
    )
    op.create_index(
        "ix_conversation_case_subject", "conversation_case_state",
        ["tenant_id", "subject_ref", "session_epoch", "updated_at"],
    )
    op.create_table(
        "conversation_case_amendment",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("case_state_id", sa.Text(), sa.ForeignKey("conversation_case_state.id"), nullable=False),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("case_id", sa.Text(), nullable=False),
        sa.Column("session_epoch", sa.Text(), nullable=False),
        sa.Column("source_message_id", sa.Text(), nullable=False),
        sa.Column("trace_id", sa.Text()),
        sa.Column("dialogue_act", sa.Text(), nullable=False),
        sa.Column("field_name", sa.Text()),
        sa.Column("old_value_json", sa.Text()),
        sa.Column("proposed_value_json", sa.Text()),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("risk", sa.Text(), nullable=False),
        sa.Column("requires_confirmation", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("provenance_json", sa.Text(), nullable=False),
        sa.Column("supersedes_id", sa.String(64), sa.ForeignKey("conversation_case_amendment.id")),
        sa.Column("observed_at", sa.Text(), nullable=False),
        sa.Column("effective_at", sa.Text()),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.UniqueConstraint(
            "tenant_id", "session_epoch", "source_message_id", "dialogue_act", "field_name",
            name="uq_conversation_case_turn",
        ),
        sa.CheckConstraint(
            "status IN ('observed','pending_confirmation','accepted','rejected','superseded')",
            name="ck_conversation_case_amendment_status",
        ),
    )
    op.create_index(
        "ix_conversation_case_amendment_timeline", "conversation_case_amendment",
        ["tenant_id", "case_id", "session_epoch", "observed_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_conversation_case_amendment_timeline", table_name="conversation_case_amendment")
    op.drop_table("conversation_case_amendment")
    op.drop_index("ix_conversation_case_subject", table_name="conversation_case_state")
    op.drop_table("conversation_case_state")
