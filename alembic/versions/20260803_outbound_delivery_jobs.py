"""Own the supplier outbox and delivery-job ledger through Alembic.

Revision ID: 20260803_outbound_jobs
Revises: 20260802_inventory_reorder
"""
from alembic import op
import sqlalchemy as sa


revision = "20260803_outbound_jobs"
down_revision = "20260802_inventory_reorder"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "outbound_message" not in tables:
        op.create_table(
            "outbound_message",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("tenant_id", sa.String(128), nullable=False),
            sa.Column("case_id", sa.String(64)),
            sa.Column("recipient", sa.Text(), nullable=False),
            sa.Column("subject", sa.Text(), nullable=False),
            sa.Column("body", sa.Text(), nullable=False),
            sa.Column("idempotency_key", sa.String(128), nullable=False),
            sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
            sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="5"),
            sa.Column("next_attempt_at", sa.String(64)),
            sa.Column("provider_ref", sa.Text()),
            sa.Column("ack_status", sa.String(32), nullable=False, server_default="awaiting"),
            sa.Column("acked_at", sa.String(64)),
            sa.Column("last_error", sa.Text()),
            sa.Column("actor_type", sa.String(32)),
            sa.Column("actor_id", sa.String(255)),
            sa.Column("transition_event", sa.String(64)),
            sa.Column("created_at", sa.String(64), nullable=False),
            sa.Column("updated_at", sa.String(64), nullable=False),
            sa.UniqueConstraint(
                "tenant_id",
                "idempotency_key",
                name="uq_outbound_message_tenant_idempotency",
            ),
        )
    indexes = {item["name"] for item in sa.inspect(bind).get_indexes("outbound_message")}
    if "ix_outbound_message_due" not in indexes:
        op.create_index(
            "ix_outbound_message_due",
            "outbound_message",
            ["tenant_id", "status", "next_attempt_at"],
        )
    if "outbound_delivery_job" not in tables:
        op.create_table(
            "outbound_delivery_job",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("tenant_id", sa.String(128), nullable=False),
            sa.Column("status", sa.String(32), nullable=False),
            sa.Column("requested_by", sa.String(255), nullable=False),
            sa.Column("limit_count", sa.Integer(), nullable=False),
            sa.Column("result_json", sa.Text()),
            sa.Column("error", sa.Text()),
            sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("started_at", sa.DateTime(timezone=True)),
            sa.Column("completed_at", sa.DateTime(timezone=True)),
        )
        op.create_index(
            "ix_outbound_delivery_job_tenant",
            "outbound_delivery_job",
            ["tenant_id", "submitted_at"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "outbound_delivery_job" in tables:
        indexes = {
            item["name"] for item in sa.inspect(bind).get_indexes("outbound_delivery_job")
        }
        if "ix_outbound_delivery_job_tenant" in indexes:
            op.drop_index(
                "ix_outbound_delivery_job_tenant",
                table_name="outbound_delivery_job",
            )
        op.drop_table("outbound_delivery_job")
    # Keep outbound_message because it contains external-delivery evidence.
