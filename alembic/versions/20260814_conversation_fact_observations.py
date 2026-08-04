"""Add append-only, expiring facts extracted from buyer conversations.

Revision ID: 20260814_conversation_facts
Revises: 20260813_canonical_semantics
"""

from alembic import op
import sqlalchemy as sa


revision = "20260814_conversation_facts"
down_revision = "20260813_canonical_semantics"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if "conversation_fact_observation" in set(sa.inspect(bind).get_table_names()):
        return
    op.create_table(
        "conversation_fact_observation",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("subject_ref", sa.Text(), nullable=False),
        sa.Column("session_id", sa.Text()),
        sa.Column("source_message_id", sa.Text(), nullable=False),
        sa.Column("trace_id", sa.Text()),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("normalized_value_json", sa.Text(), nullable=False),
        sa.Column("source_excerpt", sa.Text(), nullable=False),
        sa.Column("provenance_json", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("authority", sa.Text(), nullable=False, server_default="observation_only"),
        sa.Column("status", sa.Text(), nullable=False, server_default="active"),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "tenant_id",
            "source_message_id",
            "category",
            "normalized_value_json",
            name="uq_conversation_fact_message_value",
        ),
    )
    op.create_index(
        "ix_conversation_fact_subject",
        "conversation_fact_observation",
        ["tenant_id", "subject_ref", "status", "expires_at"],
    )
    op.create_index(
        "ix_conversation_fact_trace",
        "conversation_fact_observation",
        ["tenant_id", "trace_id", "observed_at"],
    )


def downgrade() -> None:
    # Observations follow evidence retention and survive version rollback.
    return
