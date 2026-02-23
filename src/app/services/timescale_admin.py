from __future__ import annotations

from typing import Any, Dict, List, Tuple

from sqlalchemy import text as sql_text


def _is_postgres(db) -> bool:
    try:
        name = str(getattr(getattr(db, "bind", None), "dialect", None).name or "").lower()
        return name == "postgresql"
    except Exception:
        return False


def _exec(db, statement: str, params: Dict[str, Any] | None = None) -> Tuple[bool, str | None]:
    try:
        db.execute(sql_text(statement), params or {})
        return True, None
    except Exception as exc:
        return False, str(exc)


def detect_timescale_state(db) -> Dict[str, Any]:
    state: Dict[str, Any] = {
        "dialect": str(getattr(getattr(db, "bind", None), "dialect", None).name or "unknown"),
        "postgres": _is_postgres(db),
        "timescaledb_extension": False,
        "hypertables": {},
        "continuous_aggregates": {},
    }
    if not state["postgres"]:
        return state

    try:
        row = db.execute(sql_text("SELECT extname FROM pg_catalog.pg_extension WHERE extname='timescaledb'")).fetchone()
        state["timescaledb_extension"] = bool(row)
    except Exception:
        state["timescaledb_extension"] = False

    tables = {
        "decision_trace_events": "created_at",
        "security_events": "event_time",
        "email_security_incidents": "created_at",
        "decision_logs": "valid_from",
    }
    for table in tables.keys():
        try:
            row = db.execute(
                sql_text("SELECT 1 FROM timescaledb_information.hypertables WHERE hypertable_name = :t LIMIT 1"),
                {"t": table},
            ).fetchone()
            state["hypertables"][table] = bool(row)
        except Exception:
            state["hypertables"][table] = False

    cagg_views = ["orders_hourly", "security_events_hourly"]
    for view in cagg_views:
        try:
            row = db.execute(
                sql_text("SELECT 1 FROM timescaledb_information.continuous_aggregates WHERE view_name = :v LIMIT 1"),
                {"v": view},
            ).fetchone()
            state["continuous_aggregates"][view] = bool(row)
        except Exception:
            state["continuous_aggregates"][view] = False
    return state


def apply_timescale_phase_b(db) -> Dict[str, Any]:
    """Phase B: extension, hypertables, and continuous aggregates."""
    out: Dict[str, Any] = {"applied": [], "errors": [], "skipped": []}
    if not _is_postgres(db):
        out["skipped"].append("non_postgres")
        return out

    ok, err = _exec(db, "CREATE EXTENSION IF NOT EXISTS timescaledb")
    if ok:
        out["applied"].append("extension")
    elif err:
        out["errors"].append({"step": "extension", "error": err})

    hypertable_specs: List[Tuple[str, str]] = [
        ("decision_trace_events", "created_at"),
        ("security_events", "event_time"),
        ("email_security_incidents", "created_at"),
        ("decision_logs", "valid_from"),
    ]
    for table, time_col in hypertable_specs:
        ok, err = _exec(
            db,
            "SELECT create_hypertable(:table_name, :time_col, if_not_exists => TRUE, migrate_data => TRUE)",
            {"table_name": table, "time_col": time_col},
        )
        if ok:
            out["applied"].append(f"hypertable:{table}")
        elif err:
            out["errors"].append({"step": f"hypertable:{table}", "error": err})

    cagg_sql = [
        (
            "orders_hourly",
            """
            CREATE MATERIALIZED VIEW IF NOT EXISTS orders_hourly
            WITH (timescaledb.continuous) AS
            SELECT
                time_bucket('1 hour', created_at::timestamptz) AS bucket,
                COUNT(*)::bigint AS order_count,
                COALESCE(SUM(total_cents), 0)::bigint AS revenue_cents
            FROM orders
            GROUP BY bucket
            """
        ),
        (
            "security_events_hourly",
            """
            CREATE MATERIALIZED VIEW IF NOT EXISTS security_events_hourly
            WITH (timescaledb.continuous) AS
            SELECT
                time_bucket('1 hour', event_time::timestamptz) AS bucket,
                COALESCE(severity, 'unknown') AS severity,
                COUNT(*)::bigint AS event_count
            FROM security_events
            GROUP BY bucket, severity
            """
        ),
    ]
    for view, stmt in cagg_sql:
        ok, err = _exec(db, stmt)
        if ok:
            out["applied"].append(f"cagg:{view}")
        elif err:
            out["errors"].append({"step": f"cagg:{view}", "error": err})

    return out


def apply_timescale_phase_c(db) -> Dict[str, Any]:
    """Phase C: retention + compression policies for Timescale assets."""
    out: Dict[str, Any] = {"applied": [], "errors": [], "skipped": []}
    if not _is_postgres(db):
        out["skipped"].append("non_postgres")
        return out

    compress_tables = ["decision_trace_events", "security_events", "email_security_incidents", "decision_logs"]
    for table in compress_tables:
        ok, err = _exec(
            db,
            f"ALTER TABLE {table} SET (timescaledb.compress, timescaledb.compress_segmentby = 'tenant_id')",
        )
        if ok:
            out["applied"].append(f"compression_config:{table}")
        elif err:
            out["errors"].append({"step": f"compression_config:{table}", "error": err})

    retention_targets = [
        ("decision_trace_events", "INTERVAL '2 years'"),
        ("security_events", "INTERVAL '2 years'"),
        ("email_security_incidents", "INTERVAL '2 years'"),
        ("decision_logs", "INTERVAL '2 years'"),
    ]
    for table, interval in retention_targets:
        ok, err = _exec(
            db,
            f"SELECT add_retention_policy('{table}', {interval}, if_not_exists => TRUE)",
        )
        if ok:
            out["applied"].append(f"retention:{table}")
        elif err:
            out["errors"].append({"step": f"retention:{table}", "error": err})

    compression_targets = [
        ("decision_trace_events", "INTERVAL '30 days'"),
        ("security_events", "INTERVAL '30 days'"),
        ("email_security_incidents", "INTERVAL '30 days'"),
        ("decision_logs", "INTERVAL '30 days'"),
    ]
    for table, interval in compression_targets:
        ok, err = _exec(
            db,
            f"SELECT add_compression_policy('{table}', {interval}, if_not_exists => TRUE)",
        )
        if ok:
            out["applied"].append(f"compression_policy:{table}")
        elif err:
            out["errors"].append({"step": f"compression_policy:{table}", "error": err})

    return out

