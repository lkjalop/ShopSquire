"""Tenant-scope Hippograph source tables.

Revision ID: 20260718_hippograph_tenant_scope
Revises: 20260715_payment_webhook_delivery
"""
from alembic import op
import sqlalchemy as sa

revision = "20260718_hippograph_tenant_scope"
down_revision = "20260715_payment_webhook_delivery"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in ("decision_trace_events", "recommendation_decision", "conversion_event"):
        with op.batch_alter_table(table) as batch:
            batch.add_column(sa.Column("tenant_id", sa.Text(), nullable=False, server_default="default"))
    op.create_index("ix_trace_events_tenant_created", "decision_trace_events", ["tenant_id", "created_at"])
    op.create_index("ix_recommendation_decision_tenant_created", "recommendation_decision", ["tenant_id", "created_at"])
    op.create_index("ix_conversion_event_tenant_created", "conversion_event", ["tenant_id", "created_at"])
    # Pre-tenant attribution was application-idempotent only. Remove any race-created duplicates
    # before making the tenant/order identity authoritative at the database boundary.
    op.execute(sa.text(
        "DELETE FROM conversion_event WHERE id IN ("
        "SELECT id FROM (SELECT id, ROW_NUMBER() OVER (PARTITION BY tenant_id, order_id "
        "ORDER BY created_at, id) AS rn FROM conversion_event WHERE order_id IS NOT NULL) duplicates "
        "WHERE rn > 1)"
    ))
    op.create_index("ux_conversion_event_tenant_order", "conversion_event",
                    ["tenant_id", "order_id"], unique=True)


def downgrade() -> None:
    op.drop_index("ux_conversion_event_tenant_order", table_name="conversion_event")
    op.drop_index("ix_conversion_event_tenant_created", table_name="conversion_event")
    op.drop_index("ix_recommendation_decision_tenant_created", table_name="recommendation_decision")
    op.drop_index("ix_trace_events_tenant_created", table_name="decision_trace_events")
    for table in ("conversion_event", "recommendation_decision", "decision_trace_events"):
        with op.batch_alter_table(table) as batch:
            batch.drop_column("tenant_id")
