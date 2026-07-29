"""Make durable chat history migrated, tenant scoped, and epoch scoped.

Revision ID: 20260829_tenant_chat_messages
Revises: 20260828_postgres_security_schema
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260829_tenant_chat_messages"
down_revision = "20260828_postgres_security_schema"
branch_labels = None
depends_on = None


def _table_names() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    if "chat_messages" not in _table_names():
        op.create_table(
            "chat_messages",
            sa.Column("id", sa.Text(), primary_key=True),
            sa.Column("tenant_id", sa.Text(), nullable=False, server_default="default"),
            sa.Column("uid", sa.Text(), nullable=False),
            sa.Column("session_id", sa.Text()),
            sa.Column("session_epoch", sa.Text(), nullable=False, server_default="legacy"),
            sa.Column("role", sa.Text(), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("trace_id", sa.Text()),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
        )
    else:
        existing = _columns("chat_messages")
        if "tenant_id" not in existing:
            op.add_column(
                "chat_messages",
                sa.Column("tenant_id", sa.Text(), nullable=False, server_default="default"),
            )
        if "session_epoch" not in existing:
            op.add_column(
                "chat_messages",
                sa.Column("session_epoch", sa.Text(), nullable=False, server_default="legacy"),
            )
        op.execute(
            """
            UPDATE chat_messages
            SET session_epoch = COALESCE(NULLIF(session_id, ''), 'legacy')
            WHERE session_epoch IS NULL OR session_epoch = 'legacy'
            """
        )

    op.create_index(
        "ix_chat_messages_tenant_uid_epoch_created",
        "chat_messages",
        ["tenant_id", "uid", "session_epoch", "created_at"],
        if_not_exists=True,
    )


def downgrade() -> None:
    # Conversation evidence is retained; older application versions can ignore
    # the additive authority columns.
    pass
