"""Initial core schema (SQLite + Postgres-friendly).

This repo historically bootstrapped many tables at runtime (SQLite) and via ad-hoc SQL files.
To standardize on Alembic, this migration creates the core tables used by the API.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "b17cef4ec4bc"
down_revision = "0001_init_empty"
branch_labels = None
depends_on = None


def _schema_and_bool_defaults() -> tuple[str | None, sa.ClauseElement, sa.ClauseElement]:
    bind = op.get_bind()
    dialect = getattr(getattr(bind, "dialect", None), "name", "") if bind is not None else ""
    # Keep everything in public for Postgres. SQLite ignores schemas.
    schema = "public" if "postgres" in str(dialect).lower() else None
    if "postgres" in str(dialect).lower():
        return schema, sa.text("true"), sa.text("false")
    # SQLite: use 1/0 defaults.
    return schema, sa.text("1"), sa.text("0")


def _has_table(name: str, *, schema: str | None) -> bool:
    try:
        bind = op.get_bind()
        insp = sa.inspect(bind)
        return bool(insp.has_table(name, schema=schema))
    except Exception:
        return False


def _create_table_if_missing(name: str, *cols: sa.Column, schema: str | None, **kwargs) -> None:
    if _has_table(name, schema=schema):
        return
    op.create_table(name, *cols, schema=schema, **kwargs)


def upgrade():
    schema, TRUE_D, FALSE_D = _schema_and_bool_defaults()
    # OLTP-ish core entities
    _create_table_if_missing(
        "customers",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("email", sa.Text(), nullable=True, unique=True),
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column("phone", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=True),
        schema=schema,
    )

    _create_table_if_missing(
        "products",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("sku", sa.Text(), nullable=False, unique=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("price_cents", sa.Integer(), nullable=True),
        sa.Column("currency", sa.Text(), nullable=True, server_default="USD"),
        sa.Column("image_url", sa.Text(), nullable=True),
        sa.Column("specs", sa.Text(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=True, server_default=TRUE_D),
        sa.Column("updated_at", sa.Text(), nullable=True),
        schema=schema,
    )

    _create_table_if_missing(
        "inventory",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("product_id", sa.Text(), nullable=True),
        sa.Column("stock", sa.Integer(), nullable=True),
        sa.Column("warehouse", sa.Text(), nullable=True, server_default="default"),
        sa.Column("updated_at", sa.Text(), nullable=True),
        schema=schema,
    )

    _create_table_if_missing(
        "draft_orders",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("customer_id", sa.Text(), nullable=True),
        sa.Column("line_items", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=True, server_default="draft"),
        sa.Column("created_at", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.Text(), nullable=True),
        schema=schema,
    )

    _create_table_if_missing(
        "orders",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("draft_order_id", sa.Text(), nullable=True),
        sa.Column("customer_id", sa.Text(), nullable=True),
        sa.Column("guest_email", sa.Text(), nullable=True),
        sa.Column("serial_number", sa.Text(), nullable=True),
        sa.Column("total_cents", sa.Integer(), nullable=True),
        sa.Column("currency", sa.Text(), nullable=True, server_default="USD"),
        sa.Column("status", sa.Text(), nullable=True, server_default="pending_payment"),
        sa.Column("created_at", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.Text(), nullable=True),
        schema=schema,
    )

    _create_table_if_missing(
        "order_sessions",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("uid", sa.Text(), nullable=False),
        sa.Column("order_id", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=True),
        schema=schema,
    )

    _create_table_if_missing(
        "cases",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("tenant_id", sa.Text(), nullable=True),
        sa.Column("order_id", sa.Text(), nullable=True),
        sa.Column("customer_id", sa.Text(), nullable=True),
        sa.Column("guest_email", sa.Text(), nullable=True),
        sa.Column("issue_type", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="open"),
        sa.Column("created_at", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.Text(), nullable=True),
        schema=schema,
    )

    _create_table_if_missing(
        "return_labels",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("case_id", sa.Text(), nullable=False),
        sa.Column("carrier", sa.Text(), nullable=True),
        sa.Column("tracking_number", sa.Text(), nullable=True),
        sa.Column("label_url", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=True, server_default="generated"),
        sa.Column("created_at", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.Text(), nullable=True),
        sa.Column("shipped_at", sa.Text(), nullable=True),
        sa.Column("delivered_at", sa.Text(), nullable=True),
        schema=schema,
    )

    # Audit / decision logs (kept TEXT-heavy for cross-db compatibility)
    _create_table_if_missing(
        "decision_logs",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("tenant_id", sa.Text(), nullable=True),
        sa.Column("actor_id", sa.Text(), nullable=True),
        sa.Column("actor_role", sa.Text(), nullable=True),
        sa.Column("event_type", sa.Text(), nullable=True),
        sa.Column("agent_name", sa.Text(), nullable=True),
        sa.Column("valid_from", sa.Text(), nullable=True),
        sa.Column("valid_to", sa.Text(), nullable=True),
        sa.Column("system_from", sa.Text(), nullable=True),
        sa.Column("system_to", sa.Text(), nullable=True),
        sa.Column("input_data", sa.Text(), nullable=True),
        sa.Column("retrieved_context", sa.Text(), nullable=True),
        sa.Column("agent_reasoning", sa.Text(), nullable=True),
        sa.Column("proposed_action", sa.Text(), nullable=True),
        sa.Column("policy_version", sa.Text(), nullable=True),
        sa.Column("approval_required", sa.Boolean(), nullable=True, server_default=FALSE_D),
        sa.Column("approved_by", sa.Text(), nullable=True),
        sa.Column("approved_at", sa.Text(), nullable=True),
        sa.Column("execution_status", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("evaluator_model", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Integer(), nullable=True),
        schema=schema,
    )

    _create_table_if_missing(
        "decision_audits",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("decision_id", sa.Text(), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("actor", sa.Text(), nullable=True),
        sa.Column("metadata", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=True),
        schema=schema,
    )

    # Security / incident tables
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
        schema=schema,
    )

    _create_table_if_missing(
        "iam_events",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("event_time", sa.Text(), nullable=True),
        sa.Column("event_type", sa.Text(), nullable=True),
        sa.Column("actor", sa.Text(), nullable=True),
        sa.Column("source_ip", sa.Text(), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("success", sa.Boolean(), nullable=True, server_default=FALSE_D),
        sa.Column("risk_score", sa.Integer(), nullable=True),
        sa.Column("details", sa.Text(), nullable=True),
        schema=schema,
    )

    _create_table_if_missing(
        "incidents",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("event_id", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Text(), nullable=True),
        sa.Column("severity", sa.Text(), nullable=True),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=True, server_default="open"),
        schema=schema,
    )

    # CV + trust/fraud helpers
    _create_table_if_missing(
        "cv_analyses",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("case_id", sa.Text(), nullable=False),
        sa.Column("image_sha256", sa.Text(), nullable=True),
        sa.Column("image_phash", sa.Text(), nullable=True),
        sa.Column("damage_type", sa.Text(), nullable=True),
        sa.Column("damage_location", sa.Text(), nullable=True),
        sa.Column("severity", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("serial_number", sa.Text(), nullable=True),
        sa.Column("extracted_text", sa.Text(), nullable=True),
        sa.Column("raw_labels", sa.Text(), nullable=True),
        sa.Column("model_version", sa.Text(), nullable=True),
        sa.Column("processing_time_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=True),
        schema=schema,
    )

    _create_table_if_missing(
        "customer_trust_scores",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("customer_id", sa.Text(), nullable=True),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("reasons", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.Text(), nullable=True),
        schema=schema,
    )

    _create_table_if_missing(
        "fraud_image_hashes",
        sa.Column("phash", sa.Text(), primary_key=True),
        sa.Column("first_seen_case_id", sa.Text(), nullable=True),
        sa.Column("times_seen", sa.Integer(), nullable=True, server_default=sa.text("1")),
        sa.Column("confirmed_fraud", sa.Boolean(), nullable=True, server_default=FALSE_D),
        sa.Column("created_at", sa.Text(), nullable=True),
        schema=schema,
    )

    # Misc helpers referenced by middleware/services
    _create_table_if_missing(
        "approvals",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("decision_id", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=True),
        sa.Column("approver", sa.Text(), nullable=True),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=True),
        schema=schema,
    )

    _create_table_if_missing(
        "security_observer_timeseries",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("event_time", sa.Text(), nullable=True),
        sa.Column("signal_type", sa.Text(), nullable=True),
        sa.Column("severity", sa.Text(), nullable=True),
        sa.Column("details", sa.Text(), nullable=True),
        schema=schema,
    )

    _create_table_if_missing(
        "idempotency_keys",
        sa.Column("key", sa.Text(), primary_key=True),
        sa.Column("created_at", sa.Text(), nullable=True),
        schema=schema,
    )

    _create_table_if_missing(
        "retention_policies",
        sa.Column("table_name", sa.Text(), primary_key=True),
        sa.Column("ttl_days", sa.Integer(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=True, server_default=TRUE_D),
        sa.Column("updated_at", sa.Text(), nullable=True),
        schema=schema,
    )

    _create_table_if_missing(
        "decision_trace_events",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("seq", sa.Integer(), nullable=True),
        sa.Column("trace_id", sa.Text(), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("source_type", sa.Text(), nullable=False),
        sa.Column("source_id", sa.Text(), nullable=True),
        sa.Column("target_type", sa.Text(), nullable=True),
        sa.Column("target_id", sa.Text(), nullable=True),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=True),
        schema=schema,
    )

    # Optional embeddings table used by CatalogRepository; store embedding as TEXT by default.
    _create_table_if_missing(
        "product_embeddings",
        sa.Column("product_id", sa.Text(), primary_key=True),
        sa.Column("embedding", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.Text(), nullable=True),
        schema=schema,
    )


def downgrade():
    # Best-effort down: avoid destructive drops by default.
    pass
