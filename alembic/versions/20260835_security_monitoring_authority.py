"""Persist authoritative security connector identity and monitoring delivery jobs.

Revision ID: 20260835_security_monitoring_authority
Revises: 20260834_email_security_state
"""

from alembic import op
import sqlalchemy as sa


revision = "20260835_security_monitoring_authority"
down_revision = "20260834_email_security_state"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "security_connector_subscription" not in tables:
        op.create_table(
            "security_connector_subscription",
            sa.Column("connector_id", sa.Text(), primary_key=True),
            sa.Column("tenant_id", sa.Text(), nullable=False),
            sa.Column("provider", sa.Text(), nullable=False),
            sa.Column("credential_hash", sa.Text(), nullable=False),
            sa.Column("allowed_event_families_json", sa.Text(), nullable=False),
            sa.Column("allowed_source_ids_json", sa.Text(), nullable=False),
            sa.Column("permitted_storage_targets_json", sa.Text(), nullable=False),
            sa.Column("permitted_response_actions_json", sa.Text(), nullable=False),
            sa.Column("status", sa.Text(), nullable=False, server_default="active"),
            sa.Column("credential_expires_at", sa.Text()),
            sa.Column("last_seen_at", sa.Text()),
            sa.Column("created_at", sa.Text(), server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("updated_at", sa.Text(), server_default=sa.text("CURRENT_TIMESTAMP")),
        )
        op.create_index(
            "ix_security_connector_subscription_tenant",
            "security_connector_subscription",
            ["tenant_id", "status"],
        )

    if "security_handoff_attempts" not in tables:
        op.create_table(
            "security_handoff_attempts",
            sa.Column("id", sa.Text(), primary_key=True),
            sa.Column("decision_id", sa.Text()),
            sa.Column("trace_id", sa.Text()),
            sa.Column("tenant_id", sa.Text(), nullable=False),
            sa.Column("target", sa.Text(), nullable=False),
            sa.Column("status", sa.Text(), nullable=False),
            sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("first_attempt_at", sa.Text()),
            sa.Column("last_attempt_at", sa.Text()),
            sa.Column("next_attempt_at", sa.Text()),
            sa.Column("backoff_ms", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("last_error", sa.Text()),
            sa.Column("last_http_status", sa.Integer()),
            sa.Column("payload_json", sa.Text(), nullable=False),
            sa.Column("acknowledgement_id", sa.Text()),
            sa.Column("created_at", sa.Text(), server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("updated_at", sa.Text(), server_default=sa.text("CURRENT_TIMESTAMP")),
        )
        op.create_index(
            "ix_security_handoff_due",
            "security_handoff_attempts",
            ["status", "next_attempt_at"],
        )
        op.create_index(
            "ix_security_handoff_tenant_trace",
            "security_handoff_attempts",
            ["tenant_id", "trace_id"],
        )
    else:
        columns = {item["name"] for item in sa.inspect(bind).get_columns("security_handoff_attempts")}
        if "acknowledgement_id" not in columns:
            op.add_column("security_handoff_attempts", sa.Column("acknowledgement_id", sa.Text()))


def downgrade() -> None:
    # Security delivery evidence and authoritative connector bindings are
    # intentionally retained during application rollback. The previous code
    # ignores these forward-compatible tables; deleting them would destroy the
    # incident trail precisely when rollback evidence is most important.
    return None
