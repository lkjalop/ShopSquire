"""Own connector cursor, checkpoint, outbound queue, and run-heartbeat state.

Revision ID: 20260808_connector_reliability
Revises: 20260807_inventory_quarantine
"""
from alembic import op
import sqlalchemy as sa


revision = "20260808_connector_reliability"
down_revision = "20260807_inventory_quarantine"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    return {str(item["name"]) for item in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "erp_sync_state" not in tables:
        op.create_table(
            "erp_sync_state",
            sa.Column("id", sa.Text(), primary_key=True),
            sa.Column("tenant_id", sa.Text(), nullable=False),
            sa.Column("provider", sa.Text(), nullable=False),
            sa.Column("subscription_id", sa.Text(), nullable=False, server_default="default"),
            sa.Column("entity_type", sa.Text(), nullable=False),
            sa.Column("cursor_value", sa.Text()),
            sa.Column("cursor_version", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("checkpoint_json", sa.Text()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
    else:
        cols = _columns("erp_sync_state")
        if "subscription_id" not in cols:
            op.add_column(
                "erp_sync_state",
                sa.Column("subscription_id", sa.Text(), nullable=False, server_default="default"),
            )
        if "cursor_version" not in cols:
            op.add_column(
                "erp_sync_state",
                sa.Column("cursor_version", sa.Integer(), nullable=False, server_default="0"),
            )
        if "checkpoint_json" not in cols:
            op.add_column("erp_sync_state", sa.Column("checkpoint_json", sa.Text()))

    indexes = {item["name"] for item in sa.inspect(bind).get_indexes("erp_sync_state")}
    if "idx_erp_sync_state_unique" in indexes:
        op.drop_index("idx_erp_sync_state_unique", table_name="erp_sync_state")
    if "uq_erp_sync_state_scope" not in indexes:
        op.create_index(
            "uq_erp_sync_state_scope",
            "erp_sync_state",
            ["tenant_id", "provider", "subscription_id", "entity_type"],
            unique=True,
        )

    if "erp_outbound_queue" not in tables:
        op.create_table(
            "erp_outbound_queue",
            sa.Column("id", sa.Text(), primary_key=True),
            sa.Column("tenant_id", sa.Text(), nullable=False),
            sa.Column("provider", sa.Text(), nullable=False),
            sa.Column("entity_type", sa.Text(), nullable=False),
            sa.Column("payload_json", sa.Text(), nullable=False),
            sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
            sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
            sa.Column("last_error", sa.Text()),
            sa.Column("next_attempt_at", sa.DateTime(timezone=True)),
            sa.Column("claimed_at", sa.DateTime(timezone=True)),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
    else:
        cols = _columns("erp_outbound_queue")
        if "next_attempt_at" not in cols:
            op.add_column("erp_outbound_queue", sa.Column("next_attempt_at", sa.DateTime(timezone=True)))
        if "claimed_at" not in cols:
            op.add_column("erp_outbound_queue", sa.Column("claimed_at", sa.DateTime(timezone=True)))
    indexes = {item["name"] for item in sa.inspect(bind).get_indexes("erp_outbound_queue")}
    if "idx_erp_outbound_pending" not in indexes:
        op.create_index(
            "idx_erp_outbound_pending",
            "erp_outbound_queue",
            ["tenant_id", "provider", "status", "next_attempt_at"],
        )

    if "inventory_sync_runs" in tables:
        cols = _columns("inventory_sync_runs")
        if "heartbeat_at" not in cols:
            op.add_column("inventory_sync_runs", sa.Column("heartbeat_at", sa.DateTime(timezone=True)))
        if "budget_deadline_at" not in cols:
            op.add_column("inventory_sync_runs", sa.Column("budget_deadline_at", sa.DateTime(timezone=True)))
        if "outcome_type" not in cols:
            op.add_column("inventory_sync_runs", sa.Column("outcome_type", sa.Text()))


def downgrade() -> None:
    # Operational cursor/checkpoint and queue evidence is intentionally retained.
    return
