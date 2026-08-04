"""Add encrypted raw inbound email evidence custody.

Revision ID: 20260730_email_evidence
Revises: 20260729_email_inbox
"""
from alembic import op
import sqlalchemy as sa


revision = "20260730_email_evidence"
down_revision = "20260729_email_inbox"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "inbound_email_raw_evidence",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(128), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("provider_message_id", sa.String(512), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("cipher", sa.String(32), nullable=False),
        sa.Column("encryption_key_id", sa.String(64), nullable=False),
        sa.Column("nonce_b64", sa.String(64), nullable=False),
        sa.Column("ciphertext_b64", sa.Text(), nullable=False),
        sa.Column("retention_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("legal_hold", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "provider",
            "provider_message_id",
            name="uq_inbound_email_raw_evidence_message",
        ),
    )
    op.create_index(
        "ix_inbound_email_evidence_retention",
        "inbound_email_raw_evidence",
        ["legal_hold", "retention_until"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_inbound_email_evidence_retention",
        table_name="inbound_email_raw_evidence",
    )
    op.drop_table("inbound_email_raw_evidence")
