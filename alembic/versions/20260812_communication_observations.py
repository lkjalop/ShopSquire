"""Add provider-independent supplier and buyer message observations.

Revision ID: 20260812_communication_observations
Revises: 20260811_product_lifecycle
"""
from alembic import op
import sqlalchemy as sa


revision = "20260812_communication_observations"
down_revision = "20260811_product_lifecycle"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if "communication_observation" not in set(sa.inspect(bind).get_table_names()):
        op.create_table(
            "communication_observation",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("tenant_id", sa.Text(), nullable=False),
            sa.Column("party_type", sa.Text(), nullable=False),
            sa.Column("direction", sa.Text(), nullable=False),
            sa.Column("channel", sa.Text(), nullable=False),
            sa.Column("provider_message_id", sa.Text(), nullable=False),
            sa.Column("thread_ref", sa.Text()),
            sa.Column("case_ref", sa.Text()),
            sa.Column("purpose", sa.Text(), nullable=False),
            sa.Column("consent_status", sa.Text(), nullable=False),
            sa.Column("authority", sa.Text(), nullable=False, server_default="observation_only"),
            sa.Column("security_status", sa.Text(), nullable=False),
            sa.Column("sanitized_payload_json", sa.Text(), nullable=False),
            sa.Column("evidence_ref", sa.Text()),
            sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint(
                "tenant_id", "channel", "provider_message_id",
                name="uq_communication_observation_message",
            ),
        )
        op.create_index(
            "ix_communication_observation_case",
            "communication_observation",
            ["tenant_id", "case_ref", "observed_at"],
        )


def downgrade() -> None:
    # Communications are retained according to evidence policy.
    return
