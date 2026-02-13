"""schema hardening: security/auth/misc tables and column alignment

Revision ID: 8d7f5a0df0d2
Revises: f3c206a0e6a1
Create Date: 2026-02-07 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "8d7f5a0df0d2"
down_revision = "f3c206a0e6a1"
branch_labels = None
depends_on = None


def _dialect_name() -> str:
    bind = op.get_bind()
    return str(getattr(getattr(bind, "dialect", None), "name", "") or "").lower()


def _bool_default_false() -> sa.ClauseElement:
    return sa.text("false") if "postgres" in _dialect_name() else sa.text("0")


def _has_table(name: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return bool(insp.has_table(name))


def _has_column(table: str, col_name: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    try:
        cols = insp.get_columns(table)
    except Exception:
        return False
    return any(c.get("name") == col_name for c in cols)


def _create_table_if_missing(name: str, *cols: sa.Column, **kwargs) -> None:
    if _has_table(name):
        return
    op.create_table(name, *cols, **kwargs)


def _add_column_if_missing(table: str, col: sa.Column) -> None:
    if not _has_table(table):
        return
    if _has_column(table, col.name):
        return
    op.add_column(table, col)


def _unique_constraint_exists(table: str, name: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    try:
        constraints = insp.get_unique_constraints(table)
    except Exception:
        return False
    return any(c.get("name") == name for c in constraints)


def upgrade() -> None:
    FALSE_D = _bool_default_false()

    # Security events table (used by observer + dashboards + demo seeds)
    _create_table_if_missing(
        "security_events",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("event_time", sa.Text(), nullable=True),
        sa.Column("path", sa.Text(), nullable=True),
        sa.Column("severity", sa.Text(), nullable=True),
        sa.Column("verdict_score", sa.Integer(), nullable=True),
        sa.Column("details", sa.Text(), nullable=True),
        sa.Column("escalated", sa.Boolean(), nullable=True, server_default=FALSE_D),
        sa.Column("blocked", sa.Boolean(), nullable=True, server_default=FALSE_D),
    )

    # IAM events table (auth + admin audit)
    _create_table_if_missing(
        "iam_events",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("event_time", sa.Text(), nullable=True, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("event_type", sa.Text(), nullable=True),
        sa.Column("actor", sa.Text(), nullable=True),
        sa.Column("source_ip", sa.Text(), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("success", sa.Boolean(), nullable=True, server_default=FALSE_D),
        sa.Column("risk_score", sa.Integer(), nullable=True),
        sa.Column("details", sa.Text(), nullable=True),
    )

    # Outbox/event log table
    _create_table_if_missing(
        "event_log",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("delivery_url", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=True, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("last_attempt", sa.Text(), nullable=True),
    )

    # Analytics tables (used by UI/routers)
    _create_table_if_missing(
        "search_events",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("event_time", sa.Text(), nullable=True, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("uid_hash", sa.Text(), nullable=True),
        sa.Column("query", sa.Text(), nullable=True),
        sa.Column("filters_json", sa.Text(), nullable=True),
        sa.Column("result_skus_json", sa.Text(), nullable=True),
        sa.Column("result_count", sa.Integer(), nullable=True),
        sa.Column("view_mode", sa.Text(), nullable=True),
        sa.Column("trace_id", sa.Text(), nullable=True),
        sa.Column("session_id", sa.Text(), nullable=True),
    )

    _create_table_if_missing(
        "query_clusters",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("label", sa.Text(), nullable=True),
        sa.Column("size", sa.Integer(), nullable=True),
        sa.Column("top_exemplars", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=True, server_default=sa.text("CURRENT_TIMESTAMP")),
    )

    _create_table_if_missing(
        "posthoc_outcomes",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("decision_id", sa.Text(), nullable=True),
        sa.Column("outcome_type", sa.Text(), nullable=True),
        sa.Column("outcome_value", sa.Text(), nullable=True),
        sa.Column("evidence_json", sa.Text(), nullable=True),
        sa.Column("valid_from", sa.Text(), nullable=True),
        sa.Column("valid_to", sa.Text(), nullable=True),
        sa.Column("system_from", sa.Text(), nullable=True),
        sa.Column("system_to", sa.Text(), nullable=True),
        sa.Column("actor_id", sa.Text(), nullable=True),
        sa.Column("actor_role", sa.Text(), nullable=True),
    )

    # Auth tables (previously runtime-created)
    _create_table_if_missing(
        "user_accounts",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("email", sa.Text(), nullable=False, unique=True),
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("salt", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=True, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    _create_table_if_missing(
        "session_tokens",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("token", sa.Text(), nullable=True),
        sa.Column("token_hash", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=True, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("expires_at", sa.Text(), nullable=True),
    )
    _create_table_if_missing(
        "payment_methods",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("label", sa.Text(), nullable=True),
        sa.Column("brand", sa.Text(), nullable=True),
        sa.Column("last4", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=True, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    _create_table_if_missing(
        "oauth_identities",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("provider_user_id", sa.Text(), nullable=False),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("email", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=True, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    if _has_table("oauth_identities") and not _unique_constraint_exists("oauth_identities", "uq_oauth_provider_user"):
        # SQLite cannot ALTER constraints; use batch mode copy-and-move.
        if "sqlite" in _dialect_name():
            with op.batch_alter_table("oauth_identities") as batch_op:
                batch_op.create_unique_constraint("uq_oauth_provider_user", ["provider", "provider_user_id"])
        else:
            op.create_unique_constraint("uq_oauth_provider_user", "oauth_identities", ["provider", "provider_user_id"])
    _create_table_if_missing(
        "oauth_states",
        sa.Column("state", sa.Text(), primary_key=True),
        sa.Column("return_to", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.Text(), nullable=True),
        sa.Column("code_verifier", sa.Text(), nullable=True),
        sa.Column("nonce", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=True, server_default=sa.text("CURRENT_TIMESTAMP")),
    )

    # Column alignment for previously-created tables that drifted
    # approvals: used by approvals router as durable queue
    _add_column_if_missing("approvals", sa.Column("capability", sa.Text(), nullable=True))
    _add_column_if_missing("approvals", sa.Column("payload", sa.Text(), nullable=True))
    _add_column_if_missing("approvals", sa.Column("reason", sa.Text(), nullable=True))
    _add_column_if_missing("approvals", sa.Column("created_by", sa.Text(), nullable=True))
    _add_column_if_missing("approvals", sa.Column("created_at", sa.Text(), nullable=True))
    _add_column_if_missing("approvals", sa.Column("approved_by", sa.Text(), nullable=True))
    _add_column_if_missing("approvals", sa.Column("approved_at", sa.Text(), nullable=True))

    # security_observer_timeseries: align to observer insert schema
    _add_column_if_missing("security_observer_timeseries", sa.Column("time", sa.Text(), nullable=True))
    _add_column_if_missing("security_observer_timeseries", sa.Column("event_id", sa.Text(), nullable=True))
    _add_column_if_missing("security_observer_timeseries", sa.Column("risk_adj", sa.Float(), nullable=True))
    _add_column_if_missing("security_observer_timeseries", sa.Column("insider_score", sa.Float(), nullable=True))
    _add_column_if_missing("security_observer_timeseries", sa.Column("tenant_id", sa.Text(), nullable=True))

    # idempotency_keys: ensure created_at exists (some paths create only key)
    _add_column_if_missing("idempotency_keys", sa.Column("created_at", sa.Text(), nullable=True))


def downgrade() -> None:
    # Keep downgrade non-destructive.
    pass
