"""Persist email sender trust and conversation-thread security state.

Revision ID: 20260834_email_security_state
Revises: 20260833_artifact_security_authority
"""

from alembic import op
import sqlalchemy as sa


revision = "20260834_email_security_state"
down_revision = "20260833_artifact_security_authority"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "email_sender_trust" not in tables:
        op.create_table(
            "email_sender_trust",
            sa.Column("tenant_id", sa.Text(), nullable=False),
            sa.Column("sender_domain_hash", sa.Text(), nullable=False),
            sa.Column("first_seen_at", sa.Text(), server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("seen_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("bank_change_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("oob_verified_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("reply_chain_mismatch_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("last_reply_chain_hash", sa.Text()),
            sa.Column("updated_at", sa.Text(), server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.PrimaryKeyConstraint("tenant_id", "sender_domain_hash"),
        )
    else:
        columns = {item["name"] for item in inspector.get_columns("email_sender_trust")}
        if "first_seen_at" not in columns:
            op.add_column(
                "email_sender_trust",
                sa.Column("first_seen_at", sa.Text(), nullable=True),
            )
    if "email_thread_graph_state" not in tables:
        op.create_table(
            "email_thread_graph_state",
            sa.Column("tenant_id", sa.Text(), nullable=False),
            sa.Column("thread_key", sa.Text(), nullable=False),
            sa.Column("first_seen_at", sa.Text(), server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("last_seen_at", sa.Text(), server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("last_sender_domain", sa.Text()),
            sa.Column("sender_domains_json", sa.Text()),
            sa.Column("message_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("updated_at", sa.Text(), server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.PrimaryKeyConstraint("tenant_id", "thread_key"),
        )


def downgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "email_thread_graph_state" in tables:
        op.drop_table("email_thread_graph_state")
    if "email_sender_trust" in tables:
        op.drop_table("email_sender_trust")
