from __future__ import annotations

from typing import Any, Dict

from sqlalchemy import text

from src.app.models.db import db_session


def _window_expr_and_params(db, days: int) -> tuple[str, Dict[str, Any]]:
    try:
        bind = getattr(db, "bind", None) or getattr(db, "get_bind", lambda: None)()
        dialect = str(getattr(getattr(bind, "dialect", None), "name", "") or "").lower()
    except Exception:
        dialect = ""
    if dialect.startswith("postgres"):
        return ("NOW() - (:days * INTERVAL '1 day')", {"days": days})
    return ("datetime('now', :window)", {"window": f"-{days} day"})


def generate_evidence_report(days: int = 30) -> Dict[str, Any]:
    days = max(1, min(int(days or 30), 365))
    out: Dict[str, Any] = {
        "window_days": days,
        "controls": {},
        "metrics": {},
        "samples": {},
    }
    with db_session() as db:
        window_expr, window_params = _window_expr_and_params(db, days)

        pr = db.execute(
            text(
                f"""
                SELECT
                    COUNT(*) AS runs,
                    SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) AS completed,
                    SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed
                FROM playbook_runs
                WHERE started_at >= {window_expr}
                """
            ),
            window_params,
        ).fetchone()
        runs = int(pr[0] or 0) if pr else 0
        completed = int(pr[1] or 0) if pr else 0
        failed = int(pr[2] or 0) if pr else 0

        tr = db.execute(
            text(
                f"""
                SELECT event_type, COUNT(*) AS cnt
                FROM decision_trace_events
                WHERE created_at >= {window_expr}
                GROUP BY event_type
                """
            ),
            window_params,
        ).fetchall()
        trace_counts = {str(r[0]): int(r[1] or 0) for r in tr or []}

        ch = db.execute(
            text(
                f"""
                SELECT COUNT(*) AS chained
                FROM audit_log_chain
                WHERE created_at >= {window_expr}
                """
            ),
            window_params,
        ).fetchone()
        chained = int(ch[0] or 0) if ch else 0

        priv = db.execute(
            text(
                f"""
                SELECT COUNT(*) FROM decision_audits
                WHERE action IN ('redact_user_data', 'erase_user_data')
                  AND created_at >= {window_expr}
                """
            ),
            window_params,
        ).fetchone()
        privacy_actions = int(priv[0] or 0) if priv else 0

        out["metrics"] = {
            "playbook_runs": runs,
            "playbook_completed": completed,
            "playbook_failed": failed,
            "trace_events": trace_counts,
            "immutable_audit_chain_events": chained,
            "privacy_actions": privacy_actions,
        }
        out["controls"] = {
            "pci_dss_10_audit_trails": {"status": "pass" if runs > 0 and len(trace_counts) > 0 else "warn"},
            "gdpr_article_22_transparency": {"status": "pass" if trace_counts.get("policy_verdict", 0) > 0 else "warn"},
            "soc2_cc7_operations_monitoring": {"status": "pass" if chained > 0 else "warn"},
            "gdpr_erasure_workflows": {"status": "pass" if privacy_actions > 0 else "warn"},
        }

        samp = db.execute(
            text(
                f"""
                SELECT id, playbook_id, playbook_version, status, outcome, started_at, ended_at
                FROM playbook_runs
                WHERE started_at >= {window_expr}
                ORDER BY started_at DESC
                LIMIT 20
                """
            ),
            window_params,
        ).fetchall()
        out["samples"]["playbook_runs"] = [
            {
                "id": r[0],
                "playbook_id": r[1],
                "playbook_version": r[2],
                "status": r[3],
                "outcome": r[4],
                "started_at": r[5],
                "ended_at": r[6],
            }
            for r in samp or []
        ]
    return out
