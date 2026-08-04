"""Performance indexes and PostgreSQL RLS infrastructure

Revision ID: 20260608_perf_rls
Revises: 20260608_svc_tables
Create Date: 2026-06-08

Why:
1. decision_trace_events — every Decision Trace UI tab load fetches events by
   trace_id then sorts by time.  Without a composite index this is a full-table
   scan on every page load.
2. decision_logs — chat history panel sorts by session_id + time; same problem.
3. PostgreSQL RLS on security_events / incidents / decision_logs — ensures
   application-layer tenant filtering has a database-level backstop.  Policies
   use a NULL-bypass so existing code that doesn't set app.current_tenant still
   sees all rows; full enforcement is activated by setting the GUC per-request.
   (Note: the postgres superuser role always bypasses RLS; create a non-superuser
   app role for full enforcement in production.)
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


revision = "20260608_perf_rls"
down_revision = "20260608_svc_tables"
branch_labels = None
depends_on = None


def _dialect() -> str:
    return op.get_bind().dialect.name


def _has_table(name: str) -> bool:
    return bool(sa.inspect(op.get_bind()).has_table(name))


def _has_index(table: str, index_name: str) -> bool:
    try:
        return any(
            i.get("name") == index_name
            for i in sa.inspect(op.get_bind()).get_indexes(table)
        )
    except Exception:
        return False


def _table_columns(table: str) -> set[str]:
    try:
        return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}
    except Exception:
        return set()


def upgrade() -> None:
    conn = op.get_bind()
    dialect = _dialect()

    # ── 1. Composite index: Decision Trace events ────────────────────────────
    # Every tab in the Decision Trace 10-tab UI fetches:
    #   SELECT * FROM decision_trace_events WHERE trace_id = ? ORDER BY created_at DESC
    # Without this index that is a seq-scan + sort on every page load.
    if _has_table("decision_trace_events") and not _has_index(
        "decision_trace_events", "ix_decision_trace_events_trace_created"
    ):
        conn.execute(text(
            "CREATE INDEX ix_decision_trace_events_trace_created "
            "ON decision_trace_events (trace_id, created_at DESC)"
        ))

    # ── 2. Supporting index: decision_logs by session ────────────────────────
    if _has_table("decision_logs") and not _has_index(
        "decision_logs", "ix_decision_logs_session_created"
    ):
        conn.execute(text(
            "CREATE INDEX ix_decision_logs_session_created "
            "ON decision_logs (session_id, created_at DESC)"
        ))

    # ── 3. PostgreSQL Row-Level Security ─────────────────────────────────────
    # Only runs on PostgreSQL; SQLite has no RLS support and is test-only.
    if dialect != "postgresql":
        return

    rls_targets = [
        ("security_events", "tenant_id"),
        ("incidents",       "tenant_id"),
        ("decision_logs",   "tenant_id"),
    ]

    for table, tenant_col in rls_targets:
        if not _has_table(table):
            continue
        if tenant_col not in _table_columns(table):
            continue

        policy_name = f"tenant_isolation_{table}"

        # ENABLE ROW LEVEL SECURITY is idempotent
        conn.execute(text(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY"))

        # Drop-then-recreate is the simplest idempotency strategy for policies
        conn.execute(text(f"DROP POLICY IF EXISTS {policy_name} ON {table}"))

        # Permissive USING clause:
        #   - When app.current_tenant is not set (GUC absent → returns '' with
        #     the TRUE missval arg) → NULLIF('','') = NULL → NULL IS NULL = TRUE
        #     → all rows visible (backward-safe for existing code paths).
        #   - When app.current_tenant = 'acme' → NULLIF('acme','') IS NULL = FALSE
        #     → falls through to OR tenant_id = 'acme'.
        #   - OR tenant_id IS NULL: guard for rows inserted before multi-tenancy
        #     was enforced (avoids locking out legacy data).
        conn.execute(text(
            f"CREATE POLICY {policy_name} ON {table} AS PERMISSIVE FOR ALL "
            f"USING ("
            f"  NULLIF(current_setting('app.current_tenant', TRUE), '') IS NULL"
            f"  OR {tenant_col} = current_setting('app.current_tenant', TRUE)"
            f"  OR {tenant_col} IS NULL"
            f")"
        ))


def downgrade() -> None:
    conn = op.get_bind()
    dialect = _dialect()

    for idx_name in (
        "ix_decision_trace_events_trace_created",
        "ix_decision_logs_session_created",
    ):
        try:
            conn.execute(text(f"DROP INDEX IF EXISTS {idx_name}"))
        except Exception:
            pass

    if dialect == "postgresql":
        for table in ("security_events", "incidents", "decision_logs"):
            try:
                conn.execute(text(f"DROP POLICY IF EXISTS tenant_isolation_{table} ON {table}"))
                conn.execute(text(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY"))
            except Exception:
                pass
