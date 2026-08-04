"""Production schema completion — suppliers, purchase_orders, incident tables, inventory fixes

Revision ID: 20260608_prod_schema
Revises: 20260326_add_tickets
Create Date: 2026-06-08

Why: Six categories of tables are referenced throughout production code but
were never in any alembic migration. This caused silent functional failures:

1. suppliers / supplier_products — _get_best_supplier() always returned null
   supplier with 0.0 cost, making EOQ recommendations noise.

2. purchase_orders — execute_reorder() silently discarded every generated PO.

3. reorder_point on products — monitor_stock_levels() fell back to env default
   (3 units) for every SKU instead of per-product thresholds.

4. incident SLA/assignment columns — escalation_room.py patched these at
   runtime via ALTER TABLE on every startup; fragile under parallel workers.

5. incident_evidence_attachments — was CREATE TABLE IF NOT EXISTS at runtime.

6. incident_review_tasks — new table to track human reviewer assignment and
   resolution for the escalation room (separate from cases-linked
   human_review_tasks which has FK to cases.id).

7. supplier_score_audits — was CREATE TABLE IF NOT EXISTS at runtime.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260608_prod_schema"
down_revision = "20260326_add_tickets"
branch_labels = None
depends_on = None


def _has_table(name: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return bool(insp.has_table(name))


def _has_column(table: str, col: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    try:
        cols = [c["name"] for c in insp.get_columns(table)]
        return col in cols
    except Exception:
        return False


def _has_index(table: str, name: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    try:
        return any(i.get("name") == name for i in insp.get_indexes(table))
    except Exception:
        return False


def _add_col_if_missing(table: str, col: str, coltype: sa.types.TypeEngine, **kwargs) -> None:
    if not _has_column(table, col):
        op.add_column(table, sa.Column(col, coltype, **kwargs))


def upgrade() -> None:
    # ── 1. reorder_point on products ─────────────────────────────────────────
    _add_col_if_missing("products", "reorder_point", sa.Integer(), nullable=True, server_default="3")

    # ── 2. suppliers ─────────────────────────────────────────────────────────
    if not _has_table("suppliers"):
        op.create_table(
            "suppliers",
            sa.Column("id", sa.Text(), primary_key=True),
            sa.Column("name", sa.Text(), nullable=False),
            sa.Column("contact_email", sa.Text(), nullable=True),
            sa.Column("unit_cost", sa.Float(), nullable=True, server_default="0.0"),
            sa.Column("lead_time_days", sa.Integer(), nullable=True, server_default="7"),
            sa.Column("moq", sa.Integer(), nullable=True, server_default="0"),
            sa.Column("on_time_rate", sa.Float(), nullable=True, server_default="0.0"),
            sa.Column("reliability_score", sa.Float(), nullable=True, server_default="0.0"),
            sa.Column("recent_sla_breaches", sa.Integer(), nullable=True, server_default="0"),
            sa.Column("late_deliveries_30d", sa.Integer(), nullable=True, server_default="0"),
            sa.Column("trusted", sa.Boolean(), nullable=True, server_default="1"),
            sa.Column("created_at", sa.Text(), nullable=True, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("updated_at", sa.Text(), nullable=True),
        )
        op.create_index("ix_suppliers_name", "suppliers", ["name"])

    # ── 3. supplier_products ─────────────────────────────────────────────────
    if not _has_table("supplier_products"):
        op.create_table(
            "supplier_products",
            sa.Column("id", sa.Text(), primary_key=True),
            sa.Column("supplier_id", sa.Text(), nullable=False),
            sa.Column("sku", sa.Text(), nullable=False),
            sa.Column("unit_cost_override", sa.Float(), nullable=True),
            sa.Column("moq_override", sa.Integer(), nullable=True),
            sa.Column("lead_time_override", sa.Integer(), nullable=True),
            sa.Column("preferred", sa.Boolean(), nullable=True, server_default="0"),
            sa.Column("created_at", sa.Text(), nullable=True, server_default=sa.text("CURRENT_TIMESTAMP")),
        )
        op.create_index("ix_supplier_products_sku", "supplier_products", ["sku"])
        op.create_index("ix_supplier_products_supplier_sku", "supplier_products", ["supplier_id", "sku"])

    # ── 4. purchase_orders ───────────────────────────────────────────────────
    if not _has_table("purchase_orders"):
        op.create_table(
            "purchase_orders",
            sa.Column("id", sa.Text(), primary_key=True),
            sa.Column("supplier_id", sa.Text(), nullable=True),
            sa.Column("sku", sa.Text(), nullable=False),
            sa.Column("quantity", sa.Integer(), nullable=False),
            sa.Column("unit_cost", sa.Float(), nullable=True),
            sa.Column("status", sa.Text(), nullable=False, server_default="created"),
            sa.Column("expected_delivery", sa.Text(), nullable=True),
            sa.Column("approval_ticket_id", sa.Text(), nullable=True),
            sa.Column("approved_by", sa.Text(), nullable=True),
            sa.Column("created_at", sa.Text(), nullable=True, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("updated_at", sa.Text(), nullable=True),
        )
        op.create_index("ix_purchase_orders_sku", "purchase_orders", ["sku"])
        op.create_index("ix_purchase_orders_status", "purchase_orders", ["status"])
        op.create_index("ix_purchase_orders_created", "purchase_orders", ["created_at"])

    # ── 5. supplier_score_audits ─────────────────────────────────────────────
    if not _has_table("supplier_score_audits"):
        op.create_table(
            "supplier_score_audits",
            sa.Column("id", sa.Text(), primary_key=True),
            sa.Column("created_at", sa.Text(), nullable=True, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("sku", sa.Text(), nullable=True),
            sa.Column("supplier_id", sa.Text(), nullable=True),
            sa.Column("score", sa.Float(), nullable=True),
            sa.Column("payload", sa.Text(), nullable=True),
        )
        op.create_index("ix_supplier_score_audits_sku", "supplier_score_audits", ["sku"])

    # ── 6. incidents SLA + assignment columns (idempotent) ───────────────────
    # These were previously added via runtime ALTER TABLE. Idempotent _add_col
    # is safe to run even if the column was added at runtime already.
    if _has_table("incidents"):
        _add_col_if_missing("incidents", "assigned_to", sa.Text(), nullable=True)
        _add_col_if_missing("incidents", "team", sa.Text(), nullable=True)
        _add_col_if_missing("incidents", "sla_status", sa.Text(), nullable=True)
        _add_col_if_missing("incidents", "sla_due_at", sa.Text(), nullable=True)
        _add_col_if_missing("incidents", "sla_breach_alerted_at", sa.Text(), nullable=True)
        _add_col_if_missing("incidents", "runbook_id", sa.Text(), nullable=True)
        _add_col_if_missing("incidents", "runbook_run_id", sa.Text(), nullable=True)
        _add_col_if_missing("incidents", "runbook_failure_alerted_at", sa.Text(), nullable=True)

    # ── 7. incident_evidence_attachments ─────────────────────────────────────
    if not _has_table("incident_evidence_attachments"):
        op.create_table(
            "incident_evidence_attachments",
            sa.Column("id", sa.Text(), primary_key=True),
            sa.Column("incident_id", sa.Text(), nullable=False),
            sa.Column("filename", sa.Text(), nullable=True),
            sa.Column("content_type", sa.Text(), nullable=True),
            sa.Column("file_path", sa.Text(), nullable=True),
            sa.Column("sha256", sa.Text(), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("created_by", sa.Text(), nullable=True),
            sa.Column("created_at", sa.Text(), nullable=True, server_default=sa.text("CURRENT_TIMESTAMP")),
        )
        op.create_index("ix_incident_evidence_incident_id", "incident_evidence_attachments", ["incident_id"])

    # ── 8. incident_review_tasks ─────────────────────────────────────────────
    # Purpose: track human reviewer assignment and resolution for the escalation
    # room. Separate from human_review_tasks (which has FK → cases.id) so
    # incident IDs (not case IDs) can be used without FK violations.
    if not _has_table("incident_review_tasks"):
        op.create_table(
            "incident_review_tasks",
            sa.Column("id", sa.Text(), primary_key=True),
            sa.Column("incident_id", sa.Text(), nullable=False),
            sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
            sa.Column("reviewer_id", sa.Text(), nullable=True),
            sa.Column("team", sa.Text(), nullable=True),
            sa.Column("rationale", sa.Text(), nullable=True),
            sa.Column("csat_score", sa.Integer(), nullable=True),
            sa.Column("csat_feedback", sa.Text(), nullable=True),
            sa.Column("created_at", sa.Text(), nullable=True, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("updated_at", sa.Text(), nullable=True),
        )
        op.create_index("ix_incident_review_tasks_incident_id", "incident_review_tasks", ["incident_id"])
        op.create_index("ix_incident_review_tasks_reviewer", "incident_review_tasks", ["reviewer_id"])
        op.create_index("ix_incident_review_tasks_status", "incident_review_tasks", ["status"])


    # ── 9. ragas_eval_results ────────────────────────────────────────────────
    # RAGAS evaluation scores are persisted here by services/ragas_eval.py.
    # Without this table every INSERT silently fails and Prometheus shows zeroes.
    if not _has_table("ragas_eval_results"):
        op.create_table(
            "ragas_eval_results",
            sa.Column("eval_id", sa.Text(), primary_key=True),
            sa.Column("decision_log_id", sa.Text(), nullable=True),
            sa.Column("faithfulness", sa.Float(), nullable=True),
            sa.Column("answer_relevance", sa.Float(), nullable=True),
            sa.Column("context_precision", sa.Float(), nullable=True),
            sa.Column("context_recall", sa.Float(), nullable=True),
            sa.Column("evaluator_model", sa.Text(), nullable=True, server_default="heuristic"),
            sa.Column("created_at", sa.Text(), nullable=True, server_default=sa.text("CURRENT_TIMESTAMP")),
        )
        op.create_index("ix_ragas_eval_results_decision_log_id", "ragas_eval_results", ["decision_log_id"])
        op.create_index("ix_ragas_eval_results_created_at", "ragas_eval_results", ["created_at"])

    # ── 10. ragas_baseline ───────────────────────────────────────────────────
    # Rolling quality baseline for RAGAS drift detection.
    if not _has_table("ragas_baseline"):
        op.create_table(
            "ragas_baseline",
            sa.Column("id", sa.Text(), primary_key=True),
            sa.Column("baseline_score", sa.Float(), nullable=True),
            sa.Column("updated_at", sa.Text(), nullable=True, server_default=sa.text("CURRENT_TIMESTAMP")),
        )


def downgrade() -> None:
    # Reverse in creation-order reverse
    for tbl in [
        "ragas_baseline",
        "ragas_eval_results",
        "incident_review_tasks",
        "incident_evidence_attachments",
        "supplier_score_audits",
        "purchase_orders",
        "supplier_products",
        "suppliers",
    ]:
        op.execute(f"DROP TABLE IF EXISTS {tbl}")
    # reorder_point column: leave it — dropping columns is DDL-dialect-specific
    # and the column is benign if left in place.
