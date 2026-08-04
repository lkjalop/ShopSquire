"""Add channel scheduling, procurement escalation, and payment consequence ledgers.

Revision ID: 20260852_procurement_runtime
Revises: 20260851_operational_calendar
"""
from alembic import op
import sqlalchemy as sa


revision = "20260852_procurement_runtime"
down_revision = "20260851_operational_calendar"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("outbound_message") as batch:
        batch.add_column(sa.Column("channel", sa.Text(), nullable=False, server_default="email"))
        batch.add_column(sa.Column("schedule_reason", sa.Text()))
        batch.add_column(sa.Column("sla_clock", sa.Text(), nullable=False, server_default="unknown"))
        batch.add_column(sa.Column("transport_eligible", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.create_index(
        "ix_outbound_message_channel_due", "outbound_message",
        ["tenant_id", "channel", "status", "next_attempt_at"],
    )
    op.create_table(
        "procurement_human_room",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("case_id", sa.Text(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("assigned_operator_id", sa.Text()),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("requested_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.UniqueConstraint("tenant_id", "case_id", name="uq_procurement_human_room_case"),
        sa.CheckConstraint(
            "state IN ('requested','assigned','operator_joined','responded','unavailable')",
            name="ck_procurement_human_room_state",
        ),
    )
    op.create_table(
        "procurement_human_room_event",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("room_id", sa.Text(), sa.ForeignKey("procurement_human_room.id"), nullable=False),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("case_id", sa.Text(), nullable=False),
        sa.Column("from_state", sa.Text()),
        sa.Column("to_state", sa.Text(), nullable=False),
        sa.Column("actor_type", sa.Text(), nullable=False),
        sa.Column("actor_id", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text()),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column("occurred_at", sa.Text(), nullable=False),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_procurement_room_event_idem"),
    )
    op.create_table(
        "procurement_payment_consequence",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("case_id", sa.Text(), nullable=False),
        sa.Column("plan_type", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("currency", sa.Text(), nullable=False),
        sa.Column("total_amount_cents", sa.BigInteger(), nullable=False),
        sa.Column("deposit_amount_cents", sa.BigInteger()),
        sa.Column("balance_amount_cents", sa.BigInteger()),
        sa.Column("terms_days", sa.Integer()),
        sa.Column("authorization_expires_at", sa.Text()),
        sa.Column("consequence_json", sa.Text(), nullable=False),
        sa.Column("policy_version", sa.Text(), nullable=False),
        sa.Column("status_reason", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("superseded_at", sa.Text()),
        sa.UniqueConstraint("tenant_id", "case_id", "policy_version", "created_at", name="uq_payment_consequence_version"),
    )


def downgrade() -> None:
    op.drop_table("procurement_payment_consequence")
    op.drop_table("procurement_human_room_event")
    op.drop_table("procurement_human_room")
    op.drop_index("ix_outbound_message_channel_due", table_name="outbound_message")
    with op.batch_alter_table("outbound_message") as batch:
        batch.drop_column("transport_eligible")
        batch.drop_column("sla_clock")
        batch.drop_column("schedule_reason")
        batch.drop_column("channel")
