from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import text as sql_text


ALLOWED_TABLES = {"orders", "decision_logs", "security_events"}


@dataclass
class QueryTemplate:
    intent: str
    sql: str
    tables: List[str]
    description: str


def _dialect_name(db: Any) -> str:
    try:
        return str(getattr(getattr(db, "bind", None), "dialect", None).name or "").lower()
    except Exception:
        return ""


def _ts_expr(col: str, dialect: str) -> str:
    # Normalize text timestamps to comparable values across sqlite/postgres.
    if dialect == "sqlite":
        return f"datetime(replace(replace({col}, 'T', ' '), 'Z', ''))"
    return (
        "("
        f"CASE WHEN {col} IS NULL OR {col} = '' THEN NULL "
        f"WHEN {col} LIKE '%Z' THEN replace(replace({col}, 'T', ' '), 'Z', '')::timestamp "
        f"WHEN {col} LIKE '%T%' THEN replace({col}, 'T', ' ')::timestamp "
        f"ELSE {col}::timestamp END"
        ")"
    )


def _bucket_expr_day(col: str, dialect: str) -> str:
    if dialect == "sqlite":
        return f"substr({_ts_expr(col, dialect)}, 1, 10)"
    return f"to_char(date_trunc('day', {_ts_expr(col, dialect)}), 'YYYY-MM-DD')"


def _range_pred(col: str, dialect: str) -> str:
    expr = _ts_expr(col, dialect)
    if dialect == "sqlite":
        return f"{expr} >= datetime(:start_ts) AND {expr} < datetime(:end_ts)"
    return f"{expr} >= :start_ts AND {expr} < :end_ts"


def _parse_date(value: str | None, fallback: datetime) -> datetime:
    if not value:
        return fallback
    try:
        return datetime.strptime(str(value), "%Y-%m-%d")
    except Exception:
        return fallback


def _classify(query: str) -> str:
    q = (query or "").lower()
    if any(k in q for k in ("refund", "refund rate", "returned")):
        return "refund_rate"
    if any(k in q for k in ("chargeback", "dispute rate")):
        return "chargeback_rate"
    if any(k in q for k in ("approval rate", "approve rate", "approved")):
        return "approval_rate"
    if any(k in q for k in ("autonomy", "auto approve", "human review")):
        return "autonomy_rate"
    if any(k in q for k in ("mttd", "mttr", "detect", "resolve")):
        return "security_mttd_mttr"
    if any(k in q for k in ("security", "incursion", "attack", "phish", "prompt")):
        return "security_incursions"
    if any(k in q for k in ("trend", "monthly sales", "daily sales", "revenue trend")):
        return "revenue_trend"
    return "revenue_summary"


def _build_template(intent: str, dialect: str) -> QueryTemplate:
    if intent == "refund_rate":
        return QueryTemplate(
            intent=intent,
            tables=["orders"],
            description="Refund percentage over selected range.",
            sql=(
                "SELECT COUNT(*) AS total, "
                "SUM(CASE WHEN status = 'refunded' THEN 1 ELSE 0 END) AS refunded "
                f"FROM orders WHERE {_range_pred('created_at', dialect)}"
            ),
        )
    if intent == "chargeback_rate":
        return QueryTemplate(
            intent=intent,
            tables=["orders"],
            description="Chargeback percentage over selected range.",
            sql=(
                "SELECT COUNT(*) AS total, "
                "SUM(CASE WHEN status = 'chargeback' THEN 1 ELSE 0 END) AS chargeback "
                f"FROM orders WHERE {_range_pred('created_at', dialect)}"
            ),
        )
    if intent == "approval_rate":
        return QueryTemplate(
            intent=intent,
            tables=["decision_logs"],
            description="Approval/execution percentage over selected range.",
            sql=(
                "SELECT COUNT(*) AS total, "
                "SUM(CASE WHEN execution_status IN ('approved','executed') THEN 1 ELSE 0 END) AS approved "
                f"FROM decision_logs WHERE {_range_pred('valid_from', dialect)}"
            ),
        )
    if intent == "autonomy_rate":
        autonomous_pred = (
            "COALESCE(approval_required,0) IN (0,'0',false)"
            if dialect == "sqlite"
            else "COALESCE(approval_required,false) = false"
        )
        return QueryTemplate(
            intent=intent,
            tables=["decision_logs"],
            description="Autonomy percentage (non-approval-required decisions).",
            sql=(
                "SELECT COUNT(*) AS total, "
                f"SUM(CASE WHEN {autonomous_pred} THEN 1 ELSE 0 END) AS autonomous "
                f"FROM decision_logs WHERE {_range_pred('valid_from', dialect)}"
            ),
        )
    if intent == "security_mttd_mttr":
        return QueryTemplate(
            intent=intent,
            tables=["security_events"],
            description="MTTD and MTTR based on event_time and correction_ts deltas.",
            sql=(
                "SELECT event_time, correction_ts FROM security_events "
                f"WHERE {_range_pred('event_time', dialect)} "
                "ORDER BY event_time DESC LIMIT :limit"
            ),
        )
    if intent == "security_incursions":
        return QueryTemplate(
            intent=intent,
            tables=["security_events"],
            description="Security event count by severity.",
            sql=(
                "SELECT COALESCE(severity,'unknown') AS severity, COUNT(*) AS count "
                f"FROM security_events WHERE {_range_pred('event_time', dialect)} "
                "GROUP BY 1 ORDER BY count DESC"
            ),
        )
    if intent == "revenue_trend":
        return QueryTemplate(
            intent=intent,
            tables=["orders"],
            description="Revenue trend by day.",
            sql=(
                f"SELECT {_bucket_expr_day('created_at', dialect)} AS bucket, "
                "COUNT(*) AS orders, COALESCE(SUM(total_cents),0) AS revenue_cents "
                f"FROM orders WHERE {_range_pred('created_at', dialect)} "
                "GROUP BY 1 ORDER BY 1"
            ),
        )
    return QueryTemplate(
        intent="revenue_summary",
        tables=["orders"],
        description="Revenue and order volume summary over selected range.",
        sql=(
            "SELECT COUNT(*) AS orders, COALESCE(SUM(total_cents),0) AS revenue_cents "
            f"FROM orders WHERE {_range_pred('created_at', dialect)}"
        ),
    )


def _guardrails_ok(template: QueryTemplate) -> bool:
    lower = template.sql.lower()
    if ";" in lower:
        return False
    if re.search(r"\b(drop|alter|truncate|delete|insert|update)\b", lower):
        return False
    return set(template.tables).issubset(ALLOWED_TABLES)


def _to_iso(ts: datetime) -> str:
    return ts.strftime("%Y-%m-%d %H:%M:%S")


def run_query_agent(
    *,
    db: Any,
    query: str,
    start: Optional[str] = None,
    end: Optional[str] = None,
    limit: int = 200,
) -> Dict[str, Any]:
    now = datetime.utcnow()
    dt_end = _parse_date(end, now + timedelta(days=1))
    dt_start = _parse_date(start, dt_end - timedelta(days=30))
    if dt_end <= dt_start:
        dt_end = dt_start + timedelta(days=1)
    dialect = _dialect_name(db)
    template = _build_template(_classify(query), dialect)
    if not _guardrails_ok(template):
        return {
            "status": "blocked",
            "reason": "guardrail_reject",
            "guardrails": {"allowed_tables": sorted(ALLOWED_TABLES), "allow_dml": False},
        }
    params = {"start_ts": _to_iso(dt_start), "end_ts": _to_iso(dt_end), "limit": max(10, min(2000, int(limit)))}
    rows = db.execute(sql_text(template.sql), params).mappings().all()
    return {
        "status": "ok",
        "intent": template.intent,
        "description": template.description,
        "window": {"start": dt_start.date().isoformat(), "end": dt_end.date().isoformat()},
        "sql_template_id": template.intent,
        "tables": template.tables,
        "rows": [dict(r) for r in rows],
        "guardrails": {"allowed_tables": sorted(ALLOWED_TABLES), "allow_dml": False, "template_only": True},
    }
