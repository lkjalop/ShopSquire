"""Admin status summary endpoint.

Provides ``GET /status/summary`` for the AdminDashboard overview panel.
Aggregates key platform health metrics from the decision trace, security
events, and session tables.
"""
from __future__ import annotations

import time
from typing import Any, Dict

from fastapi import APIRouter, Depends
from sqlalchemy import text as sql_text

from src.app.models.db import db_session
from src.app.security.auth import require_role, ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER

router = APIRouter(tags=["status"])


@router.get("/status/summary")
@router.get("/api/v1/status/summary")
def status_summary(
    _role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    """Aggregate platform health metrics for the admin dashboard."""
    result: Dict[str, Any] = {
        "email_xdr": {"warnings": 0},
        "outbound_anomalies": 0,
        "active_sessions": 0,
        "decision_traces_24h": 0,
        "incidents_open": 0,
        "risk_posture": {},
        "collected_at": time.time(),
    }

    try:
        with db_session() as session:
            # Decision traces in last 24h
            try:
                row = session.execute(sql_text(
                    "SELECT COUNT(*) FROM decision_trace_events "
                    "WHERE created_at >= datetime('now', '-1 day')"
                )).scalar()
                result["decision_traces_24h"] = int(row or 0)
            except Exception:
                pass

            # Active sessions (non-expired)
            try:
                row = session.execute(sql_text(
                    "SELECT COUNT(*) FROM session_tokens "
                    "WHERE expires_at > datetime('now')"
                )).scalar()
                result["active_sessions"] = int(row or 0)
            except Exception:
                pass

            # Open incidents
            try:
                row = session.execute(sql_text(
                    "SELECT COUNT(*) FROM incidents WHERE status NOT IN ('closed', 'resolved')"
                )).scalar()
                result["incidents_open"] = int(row or 0)
            except Exception:
                pass

            # Email security warnings (last 24h)
            try:
                row = session.execute(sql_text(
                    "SELECT COUNT(*) FROM decision_trace_events "
                    "WHERE event_type IN ('email_security_scan', 'dmarc_failure') "
                    "AND created_at >= datetime('now', '-1 day')"
                )).scalar()
                result["email_xdr"]["warnings"] = int(row or 0)
            except Exception:
                pass

            # Outbound anomalies (last 24h)
            try:
                row = session.execute(sql_text(
                    "SELECT COUNT(*) FROM decision_trace_events "
                    "WHERE event_type = 'outbound_anomaly' "
                    "AND created_at >= datetime('now', '-1 day')"
                )).scalar()
                result["outbound_anomalies"] = int(row or 0)
            except Exception:
                pass

    except Exception:
        pass

    # Risk posture from risk register
    try:
        from src.app.routers.admin_grc import get_latest_risk_bands
        result["risk_posture"] = get_latest_risk_bands()
    except Exception:
        pass

    return result
