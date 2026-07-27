"""Add durable email correlation and quarantine disposition ledgers.

Revision ID: 20260731_email_controls
Revises: 20260730_email_evidence
"""
from alembic import op
import sqlalchemy as sa


revision = "20260731_email_controls"
down_revision = "20260730_email_evidence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "inbound_email_inbox",
        sa.Column("enrichment_status", sa.String(32), nullable=False, server_default="pending"),
    )
    op.add_column(
        "inbound_email_inbox",
        sa.Column("enrichment_attempts", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("inbound_email_inbox", sa.Column("enrichment_error", sa.Text()))
    op.create_table(
        "outbound_email_correlation",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(128), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("provider_message_id", sa.String(512), nullable=False),
        sa.Column("provider_thread_id", sa.String(512)),
        sa.Column("fulfillment_case_id", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "tenant_id", "provider", "provider_message_id",
            name="uq_outbound_email_correlation_message",
        ),
    )
    op.create_index(
        "ix_outbound_email_correlation_thread",
        "outbound_email_correlation",
        ["tenant_id", "provider", "provider_thread_id"],
    )
    op.create_table(
        "inbound_email_quarantine_disposition",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(128), nullable=False),
        sa.Column("inbox_id", sa.String(64), nullable=False),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("actor_id", sa.String(255), nullable=False),
        sa.Column("note", sa.Text()),
        sa.Column("fresh_case_id", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "inbox_id", name="uq_inbound_quarantine_disposition"),
    )


def downgrade() -> None:
    op.drop_table("inbound_email_quarantine_disposition")
    op.drop_index(
        "ix_outbound_email_correlation_thread",
        table_name="outbound_email_correlation",
    )
    op.drop_table("outbound_email_correlation")
    op.drop_column("inbound_email_inbox", "enrichment_error")
    op.drop_column("inbound_email_inbox", "enrichment_attempts")
    op.drop_column("inbound_email_inbox", "enrichment_status")
