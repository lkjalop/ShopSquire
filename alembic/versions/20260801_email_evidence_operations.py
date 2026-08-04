"""Add immutable audit records for evidence and enrichment operations.

Revision ID: 20260801_email_ops
Revises: 20260731_email_controls
"""
from alembic import op
import sqlalchemy as sa


revision = "20260801_email_ops"
down_revision = "20260731_email_controls"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "email_evidence_operation_audit",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(128), nullable=False),
        sa.Column("evidence_id", sa.String(64)),
        sa.Column("inbox_id", sa.String(64)),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("actor_id", sa.String(255), nullable=False),
        sa.Column("purpose", sa.Text(), nullable=False),
        sa.Column("metadata_json", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_email_evidence_audit_lookup",
        "email_evidence_operation_audit",
        ["tenant_id", "evidence_id", "created_at"],
    )
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            """
            CREATE OR REPLACE FUNCTION protect_inbound_email_evidence_identity()
            RETURNS trigger AS $$
            BEGIN
              IF NEW.id <> OLD.id
                 OR NEW.tenant_id <> OLD.tenant_id
                 OR NEW.provider <> OLD.provider
                 OR NEW.provider_message_id <> OLD.provider_message_id
                 OR NEW.sha256 <> OLD.sha256
                 OR NEW.cipher <> OLD.cipher
                 OR NEW.retention_until <> OLD.retention_until
                 OR NEW.created_at <> OLD.created_at THEN
                RAISE EXCEPTION 'immutable inbound email evidence identity';
              END IF;
              RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
            """
        )
        op.execute(
            """
            CREATE TRIGGER trg_protect_inbound_email_evidence_identity
            BEFORE UPDATE ON inbound_email_raw_evidence
            FOR EACH ROW EXECUTE FUNCTION protect_inbound_email_evidence_identity()
            """
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            "DROP TRIGGER IF EXISTS trg_protect_inbound_email_evidence_identity "
            "ON inbound_email_raw_evidence"
        )
        op.execute("DROP FUNCTION IF EXISTS protect_inbound_email_evidence_identity()")
    op.drop_index(
        "ix_email_evidence_audit_lookup",
        table_name="email_evidence_operation_audit",
    )
    op.drop_table("email_evidence_operation_audit")
