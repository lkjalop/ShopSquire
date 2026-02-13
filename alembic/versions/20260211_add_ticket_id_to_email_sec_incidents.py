"""add ticket_id to email security incidents

Revision ID: c7d8e9f0a2b3
Revises: b6c7d8e9f0a1
Create Date: 2026-02-11 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "c7d8e9f0a2b3"
down_revision = "b6c7d8e9f0a1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    try:
        if insp.has_table("email_security_incidents"):
            cols = {c.get("name") for c in insp.get_columns("email_security_incidents")}
            if "ticket_id" not in cols:
                op.add_column("email_security_incidents", sa.Column("ticket_id", sa.Text(), nullable=True))
            # Optional index for joins/lookups by ticket
            try:
                op.create_index("ix_email_sec_inc_ticket", "email_security_incidents", ["ticket_id"], unique=False)
            except Exception:
                pass
    except Exception:
        # As a fallback for engines that don't support reflection well
        try:
            op.execute(sa.text("ALTER TABLE email_security_incidents ADD COLUMN ticket_id TEXT"))
            try:
                op.create_index("ix_email_sec_inc_ticket", "email_security_incidents", ["ticket_id"], unique=False)
            except Exception:
                pass
        except Exception:
            pass


def downgrade() -> None:
    # No destructive downgrade to preserve data; keep column if present
    pass
