"""Add the tenant-scoped inbound email inbox.

Revision ID: 20260729_email_inbox
Revises: 20260728_forecast_identity
"""
from alembic import op
import sqlalchemy as sa


revision = "20260729_email_inbox"
down_revision = "20260728_forecast_identity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "inbound_email_inbox",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(128), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("provider_message_id", sa.String(512), nullable=False),
        sa.Column("subscription_id", sa.String(512)),
        sa.Column("fulfillment_case_id", sa.String(64)),
        sa.Column("status", sa.String(64), nullable=False),
        sa.Column("security_route", sa.String(64)),
        sa.Column("sanitized_payload_json", sa.Text(), nullable=False),
        sa.Column("security_verdict_json", sa.Text()),
        sa.Column("raw_evidence_ref", sa.String(255), nullable=False),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "provider",
            "provider_message_id",
            name="uq_inbound_email_provider_message",
        ),
    )
    op.create_index(
        "ix_inbound_email_tenant_status",
        "inbound_email_inbox",
        ["tenant_id", "status", "received_at"],
    )
    op.create_index(
        "ix_inbound_email_case",
        "inbound_email_inbox",
        ["tenant_id", "fulfillment_case_id", "received_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_inbound_email_case", table_name="inbound_email_inbox")
    op.drop_index("ix_inbound_email_tenant_status", table_name="inbound_email_inbox")
    op.drop_table("inbound_email_inbox")
