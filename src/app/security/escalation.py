from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime
from typing import Dict

from sqlalchemy import text as sql_text

from src.app.models.db import get_engine
from src.app.observability.metrics import record_incident_alert

_log = logging.getLogger("shopsquire.security.escalation")
from src.app.utils.webhook import send_webhook
from src.app.services.ticketing import TicketingAgent
from src.app.services.decision_log import log_decision
from src.app.security.telemetry_emit import emit_security_telemetry
from src.app.services.security_playbooks import select_playbook, build_evidence_snapshot
from src.app.models.init_db import ensure_metadata
from src.app.routers.escalation_room import create_incident_record


def _load_webhooks() -> list[str]:
    try:
        from pathlib import Path

        cfg_text = Path("config/webhooks.yml").read_text()
        try:
            import yaml as _yaml

            cfg = _yaml.safe_load(cfg_text)
        except Exception:
            cfg = json.loads(cfg_text)
        return cfg.get("webhooks", {}).get("security_events", []) or []
    except Exception:
        return []


def _should_escalate(severity: str, score: float) -> bool:
    min_sev = os.getenv("SECURITY_ESCALATE_MIN_SEVERITY", "high")
    min_score = float(os.getenv("SECURITY_ESCALATE_MIN_SCORE", "70"))
    sev_rank = {"info": 0, "warn": 1, "high": 2, "critical": 3}
    return sev_rank.get(severity, 0) >= sev_rank.get(min_sev, 2) or score >= min_score


def _should_review(severity: str, score: float) -> bool:
    min_sev = os.getenv("SECURITY_REVIEW_MIN_SEVERITY", "warn")
    min_score = float(os.getenv("SECURITY_REVIEW_MIN_SCORE", "30"))
    sev_rank = {"info": 0, "warn": 1, "high": 2, "critical": 3}
    return sev_rank.get(severity, 0) >= sev_rank.get(min_sev, 1) or score >= min_score


def auto_route_security_event(event_id: str, severity: str, score: float, details: Dict) -> None:
    if str(os.getenv("SECURITY_AUTOROUTE_ENABLED", "true")).lower() in ("0", "false", "no"):
        return
    if _should_escalate(severity, score):
        _create_incident(event_id, severity, details, status="open", escalated=True)
    elif _should_review(severity, score):
        _create_incident(event_id, severity, details, status="review", escalated=False)


def _create_incident(event_id: str, severity: str, details: Dict, status: str, escalated: bool) -> None:
    eng = get_engine()
    incident_id = str(uuid.uuid4())
    title = f"Auto {status}: {severity} security event"
    # Alembic is the source of truth for non-SQLite DBs; keep SQLite-only bootstrap.
    try:
        if getattr(eng, "dialect", None) is not None and eng.dialect.name == "sqlite":
            try:
                ensure_metadata()
            except Exception:
                pass
            try:
                with eng.begin() as conn:
                    conn.execute(
                        sql_text(
                            "CREATE TABLE IF NOT EXISTS security_events ("
                            "id TEXT PRIMARY KEY, "
                            "event_time TEXT DEFAULT CURRENT_TIMESTAMP, "
                            "path TEXT, "
                            "severity TEXT, "
                            "verdict_score INT, "
                            "details TEXT, "
                            "escalated INTEGER DEFAULT 0, "
                            "blocked INTEGER DEFAULT 0"
                            ")"
                        )
                    )
                    conn.execute(
                        sql_text(
                            "CREATE TABLE IF NOT EXISTS incidents ("
                            "id TEXT PRIMARY KEY, "
                            "event_id TEXT, "
                            "created_at TEXT DEFAULT CURRENT_TIMESTAMP, "
                            "created_by TEXT, "
                            "severity TEXT, "
                            "title TEXT, "
                            "description TEXT, "
                            "status TEXT DEFAULT 'open'"
                            ")"
                        )
                    )
            except Exception:
                pass
    except Exception:
        pass
    try:
        desc = json.dumps(details or {}, ensure_ascii=False)
    except Exception:
        desc = str(details)
    ticket_id = None
    customer_tier = None
    try:
        if isinstance(details, dict):
            customer_tier = details.get("customer_tier")
    except Exception:
        customer_tier = None
    # ── Enrich context with DREAD evidence trail ──
    _incident_context = details if isinstance(details, dict) else {"details": details}
    try:
        from src.app.security.dread_scorer import compute_dread
        _sec_block = _incident_context.get("security") or _incident_context.get("security_analysis") or {}
        _dread_signals: Dict = {}
        _cv_signals: Dict = {}
        if isinstance(_sec_block, dict):
            _dread_signals = _sec_block.get("signals") or {}
            _cv_signals = _sec_block.get("cv_signals") or {}
        elif isinstance(_incident_context.get("signals"), dict):
            _dread_signals = _incident_context["signals"]
        if _dread_signals:
            _dread = compute_dread(
                signals=_dread_signals,
                cv_signals=_cv_signals or None,
                severity=severity,
                actor_context=_incident_context.get("actor_context") or None,
            )
            _incident_context = {**_incident_context, "dread": _dread}
    except Exception:
        pass
    try:
        incident = create_incident_record(
            case_id=None,
            trace_id=event_id,
            reason=f"security_{status}",
            context=_incident_context,
            created_by="system",
            severity=severity,
            title=title,
            dedupe_by_event=True,
        )
        incident_id = str(incident.get("incident_id") or incident_id)
    except Exception as _inc_exc:
        # Incident service is the single authoritative path — do not shadow-insert.
        # Log the failure so operators can investigate; downstream webhooks/telemetry
        # still fire so the event is not silently lost.
        _log.warning(
            "create_incident_record failed for event_id=%s severity=%s; "
            "incident NOT persisted via legacy fallback. Error: %s",
            event_id,
            severity,
            str(_inc_exc)[:300],
        )
    with eng.begin() as conn:
        if escalated:
            try:
                conn.execute(
                    sql_text("UPDATE security_events SET escalated = 1 WHERE id = :id"),
                    {"id": event_id},
                )
            except Exception:
                pass
    try:
        if escalated or status == "review":
            tenant = details.get("tenant_id") if isinstance(details, dict) else None
            signals = {}
            try:
                if isinstance(details, dict):
                    sec = details.get("security") or details.get("security_analysis") or {}
                    signals = sec.get("signals") if isinstance(sec, dict) else {}
            except Exception:
                signals = {}
            playbook = select_playbook(signals, severity=severity)
            evidence_snapshot = build_evidence_snapshot(details if isinstance(details, dict) else {})
            t = TicketingAgent().create_ticket(
                title=title,
                description=desc,
                severity=severity,
                tenant_id=tenant,
                reason_code=f"security_{status}",
                trace_id=event_id,
                policy_version="v1",
                customer_tier=customer_tier,
                playbook=playbook,
                evidence_snapshot=evidence_snapshot,
            )
            ticket_id = t.id
    except Exception:
        pass
    try:
        record_incident_alert("security", severity)
    except Exception:
        pass
    try:
        from src.app.utils.webhook import parse_senders

        senders = parse_senders("config/webhooks.yml", "security_events")
    except Exception:
        senders = []
    for s in senders or []:
        try:
            send_webhook(
                s.get("url"),
                {
                    "event": f"security.auto_{status}",
                    "event_id": event_id,
                    "incident_id": incident_id,
                    "severity": severity,
                    "title": title,
                    "description": desc,
                    "timestamp": datetime.utcnow().isoformat(),
                },
                secret=s.get("secret"),
                key_id=s.get("key_id"),
            )
        except Exception:
            pass
    # Emit to external telemetry (fire-and-forget)
    try:
        emit_security_telemetry(
            {
                "event": f"security.auto_{status}",
                "event_id": event_id,
                "incident_id": incident_id,
                "severity": severity,
                "title": title,
                "status": status,
                "timestamp": datetime.utcnow().isoformat(),
            }
        )
    except Exception:
        pass
    # Persist a bitemporal decision trace for security auto-routing
    try:
        log_decision(
            agent_name="security_escalation_agent",
            input_data={"event_id": event_id, "severity": severity, "status": status},
            retrieved_context={**(details or {}), "customer_tier": customer_tier},
            proposed_action={"incident_id": incident_id, "ticket_id": ticket_id, "escalated": escalated},
            agent_reasoning=f"auto_route_security_event status={status}",
            policy_version="v1",
            approval_required=False,
            execution_status="executed",
            tenant_id=details.get("tenant_id") if isinstance(details, dict) else None,
        )
    except Exception:
        pass
