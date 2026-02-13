"""email security incidents persistence

Revision ID: b6c7d8e9f0a1
Revises: a8c1d2e3f4b5
Create Date: 2026-02-10 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "b6c7d8e9f0a1"
down_revision = "a8c1d2e3f4b5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if insp.has_table("email_security_incidents"):
        return

    op.create_table(
        "email_security_incidents",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("tenant_id", sa.Text(), nullable=True),
        sa.Column("provider", sa.Text(), nullable=True),
        sa.Column("supplier_key_hash", sa.Text(), nullable=True),
        sa.Column("conversation_id_hash", sa.Text(), nullable=True),
        sa.Column("message_id_hash", sa.Text(), nullable=True),
        sa.Column("severity", sa.Text(), nullable=False),
        sa.Column("risk_band", sa.Text(), nullable=True),
        sa.Column("tags_json", sa.Text(), nullable=False),
        sa.Column("reasons_json", sa.Text(), nullable=False),
        sa.Column("evidence_json", sa.Text(), nullable=False),
        sa.Column("playbook_id", sa.Text(), nullable=True),
        sa.Column("playbook_title", sa.Text(), nullable=True),
        sa.Column("ticket_created", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("ticket_rate_limited", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("ticket_deduped", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.Text(), nullable=True, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    try:
        op.create_index("ix_email_sec_inc_tenant_created", "email_security_incidents", ["tenant_id", "created_at"])
    except Exception:
        pass
    try:
        op.create_index("ix_email_sec_inc_supplier_created", "email_security_incidents", ["supplier_key_hash", "created_at"])
    except Exception:
        pass
    try:
        op.create_index("ix_email_sec_inc_msg", "email_security_incidents", ["message_id_hash"])
    except Exception:
        pass


def downgrade() -> None:
    # Non-destructive
    pass

