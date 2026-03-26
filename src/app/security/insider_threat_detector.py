"""IT-DET — Insider Threat Detection Engine.

Implements five detection controls per COMPLIANCE-INSIDER-THREAT.md:

  IT-DET-01  Off-hours privileged access
  IT-DET-02  Bulk data export
  IT-DET-03  Supplier baseline / config file drift
  IT-DET-04  Alert / ticket suppression (duplicate-close pattern)
  IT-DET-05  Prompt version hash mismatch

Every detected signal is:
  1. Logged via structlog / stdlib logger
  2. Emitted to the SIEM adapter (Splunk HEC / webhook)
  3. Written to the tamper-evident audit chain on severity ≥ critical
  4. Recorded as a Prometheus counter (shopsquire_insider_threat_signals_total)

Framework alignment
-------------------
  ISO 27001:2022  A.8.15 (monitoring), A.8.16 (monitoring activities)
  NIST SP 800-53  AU-6, SI-4, PS-3
  PCI DSS 4.0     Req 10.7 (detect / respond to failures of audit controls)
  CISA Insider Threat Guide 2024
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Signal data model
# ---------------------------------------------------------------------------

@dataclass
class InsiderThreatSignal:
    signal_type: str
    actor:       str
    resource:    str
    severity:    str = "high"        # info / medium / high / critical
    context:     Dict[str, Any] = field(default_factory=dict)
    timestamp:   str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "signal_type": self.signal_type,
            "actor": self.actor,
            "resource": self.resource,
            "severity": self.severity,
            "context": self.context,
            "timestamp": self.timestamp,
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _non_local() -> bool:
    return str(os.getenv("APP_ENV", "local") or "local").lower() not in (
        "local", "dev", "development", "test", "testing"
    )


def _emit(signal: InsiderThreatSignal) -> None:
    """Persist and propagate a signal.  Never raises — detection must not
    interrupt the request that triggered it."""
    try:
        # 1. Structured log
        logger.warning(
            "insider_threat signal=%s actor=%s resource=%s severity=%s context=%s",
            signal.signal_type, signal.actor, signal.resource,
            signal.severity, json.dumps(signal.context),
        )

        # 2. Prometheus counter
        try:
            from src.app.observability.metrics import insider_threat_signals_total
            actor_hash = hashlib.sha256(signal.actor.encode()).hexdigest()[:12]
            insider_threat_signals_total.labels(
                signal_type=signal.signal_type,
                severity=signal.severity,
                actor_hash=actor_hash,
            ).inc()
        except Exception:
            pass

        # 3. SIEM adapter
        try:
            from src.app.security.siem_adapter import emit_siem_event
            emit_siem_event(
                event_type=f"insider_threat:{signal.signal_type}",
                severity=signal.severity,
                actor=signal.actor,
                resource=signal.resource,
                context=signal.context,
            )
        except Exception:
            pass

        # 4. Audit chain — critical signals only (prevents spam on medium/info)
        if signal.severity == "critical":
            try:
                from src.app.models.db import db_session
                from src.app.security.audit_chain import chain_new_record
                record_id = hashlib.sha256(
                    f"{signal.signal_type}{signal.actor}{signal.timestamp}".encode()
                ).hexdigest()[:16]
                with db_session() as db:
                    chain_new_record(
                        db,
                        record_id=record_id,
                        decision_id="insider_threat",
                        action=signal.signal_type,
                        actor=signal.actor,
                        metadata=json.dumps(signal.context),
                        created_at=signal.timestamp,
                    )
            except Exception:
                pass

    except Exception as exc:
        logger.error("insider_threat_detector _emit failed: %s", exc)


# ---------------------------------------------------------------------------
# IT-DET-01 — Off-hours privileged access
# ---------------------------------------------------------------------------
# Business hours: AEST = UTC+10 → 08:00–20:00 AEST = 22:00–10:00 UTC
# Configurable via BH_START_UTC / BH_END_UTC env vars.
# ---------------------------------------------------------------------------

def _business_hours_utc() -> tuple[int, int]:
    """Return (start_hour_utc, end_hour_utc) exclusive upper bound."""
    try:
        start = int(os.getenv("BH_START_UTC", "22") or 22)  # 08:00 AEST
        end   = int(os.getenv("BH_END_UTC",   "10") or 10)  # 20:00 AEST
        return start, end
    except Exception:
        return 22, 10


def _is_within_business_hours(utc_hour: int) -> bool:
    start, end = _business_hours_utc()
    if start > end:                      # wraps midnight (AEST wraps)
        return utc_hour >= start or utc_hour < end
    return start <= utc_hour < end


def detect_off_hours_admin(
    *,
    actor: str,
    action: str,
    ip: str,
    role: str,
    utc_hour: Optional[int] = None,
) -> Optional[InsiderThreatSignal]:
    """Fire when a privileged role (owner/developer/admin) acts outside
    business hours."""
    privileged = {"owner", "developer", "admin"}
    if role.lower() not in privileged:
        return None
    hour = utc_hour if utc_hour is not None else datetime.now(timezone.utc).hour
    if not _is_within_business_hours(hour):
        signal = InsiderThreatSignal(
            signal_type="off_hours_admin_access",
            actor=actor,
            resource=action,
            severity="medium",
            context={
                "role": role,
                "ip": ip,
                "hour_utc": hour,
                "business_hours": f"{_business_hours_utc()[0]}:00–{_business_hours_utc()[1]}:00 UTC",
            },
        )
        _emit(signal)
        return signal
    return None


# ---------------------------------------------------------------------------
# IT-DET-02 — Bulk data export
# ---------------------------------------------------------------------------

_BULK_EXPORT_THRESHOLD = max(1, int(os.getenv("BULK_EXPORT_THRESHOLD", "1000") or 1000))


def detect_bulk_export(
    *,
    actor: str,
    resource: str,
    record_count: int,
    threshold: Optional[int] = None,
) -> Optional[InsiderThreatSignal]:
    """Fire when a single request or export job touches ≥ threshold records."""
    limit = threshold if threshold is not None else _BULK_EXPORT_THRESHOLD
    if record_count < limit:
        return None
    signal = InsiderThreatSignal(
        signal_type="bulk_data_export",
        actor=actor,
        resource=resource,
        severity="critical",
        context={
            "record_count": record_count,
            "threshold": limit,
        },
    )
    _emit(signal)
    return signal


# ---------------------------------------------------------------------------
# IT-DET-03 — Audit chain tampering
# ---------------------------------------------------------------------------

def detect_audit_chain_tamper(db_session_ctx) -> Optional[InsiderThreatSignal]:
    """Re-verify the full audit chain.  Returns a signal if tampering is found.

    Intended to be called from the Celery periodic task every 5 minutes.
    """
    try:
        from src.app.security.audit_chain import verify_chain
        from src.app.observability.metrics import audit_chain_verifications_total
    except ImportError:
        return None

    try:
        result = verify_chain(db_session_ctx)
        valid = result.get("valid", True)
        try:
            label = "valid" if valid else "tampered"
            audit_chain_verifications_total.labels(result=label).inc()
        except Exception:
            pass

        if not valid:
            signal = InsiderThreatSignal(
                signal_type="audit_chain_tamper_detected",
                actor="system",
                resource="decision_audits",
                severity="critical",
                context={
                    "first_broken_id": result.get("first_broken_id"),
                    "checked": result.get("checked"),
                    "reason": result.get("reason"),
                    "verification_result": result,
                },
            )
            _emit(signal)
            return signal
    except Exception as exc:
        logger.error("detect_audit_chain_tamper error: %s", exc)
        try:
            from src.app.observability.metrics import audit_chain_verifications_total
            audit_chain_verifications_total.labels(result="error").inc()
        except Exception:
            pass

    return None


# ---------------------------------------------------------------------------
# IT-DET-04 — Alert / ticket suppression detection
# ---------------------------------------------------------------------------

def detect_alert_suppression(
    *,
    actor: str,
    critical_closes_in_window: int,
    window_minutes: int = 60,
    threshold: int = 2,
) -> Optional[InsiderThreatSignal]:
    """Fire when the same actor closes more than *threshold* critical tickets
    within *window_minutes*.

    Call this from the ticket-close handler with a Redis sliding-window count.
    """
    if critical_closes_in_window <= threshold:
        return None
    signal = InsiderThreatSignal(
        signal_type="alert_suppression_pattern",
        actor=actor,
        resource="tickets/critical",
        severity="high",
        context={
            "critical_closes": critical_closes_in_window,
            "window_minutes": window_minutes,
            "threshold": threshold,
        },
    )
    _emit(signal)
    return signal


def check_self_close_critical(
    *,
    actor: str,
    ticket_created_by: str,
    ticket_priority: str,
    ticket_topic: str,
) -> Optional[InsiderThreatSignal]:
    """Prevent an actor closing their own critical fraud/BEC ticket."""
    high_risk_topics = {"fraud", "bec", "supply_chain", "insider_threat"}
    if ticket_priority != "critical":
        return None
    if ticket_topic.lower() not in high_risk_topics:
        return None
    if actor != ticket_created_by:
        return None
    signal = InsiderThreatSignal(
        signal_type="self_close_critical_ticket",
        actor=actor,
        resource=f"ticket/critical/{ticket_topic}",
        severity="high",
        context={
            "ticket_created_by": ticket_created_by,
            "ticket_priority": ticket_priority,
            "ticket_topic": ticket_topic,
        },
    )
    _emit(signal)
    return signal


# ---------------------------------------------------------------------------
# IT-DET-05 — Prompt version hash mismatch (see also prompt_registry.py)
# ---------------------------------------------------------------------------

def detect_prompt_tampering(
    *,
    prompt_id: str,
    expected_hash: str,
    actual_hash: str,
) -> Optional[InsiderThreatSignal]:
    """Fire when a registered system prompt's content hash doesn't match the
    expected value on record.  Called by prompt_registry.verify_all()."""
    if expected_hash == actual_hash:
        return None
    signal = InsiderThreatSignal(
        signal_type="prompt_hash_mismatch",
        actor="system",
        resource=f"prompt/{prompt_id}",
        severity="critical",
        context={
            "prompt_id": prompt_id,
            "expected_hash": expected_hash[:16] + "...",
            "actual_hash":   actual_hash[:16]   + "...",
        },
    )
    _emit(signal)
    return signal


# ---------------------------------------------------------------------------
# IT-DET-02b — Agent session context injection
# ---------------------------------------------------------------------------

import re as _re

_SESSION_INJECT_PATTERNS = [
    _re.compile(r"(?i)ignore\s+(?:previous|all)\s+instructions"),
    _re.compile(r"(?i)new\s+system\s+prompt"),
    _re.compile(r"(?i)disregard\s+your\s+instructions"),
    _re.compile(r"(?i)you\s+are\s+now\s+(?:in\s+)?(?:admin|dev(?:eloper)?|root)\s*(?:mode|override)?"),
    _re.compile(r"(?i)developer\s+override"),
    _re.compile(r"(?i)bypass\s+(?:fraud|security|check|filter)"),
    _re.compile(r"(?i)auto.?approve\s+all"),
    _re.compile(r"(?i)whitelist\s+all"),
]


def check_session_context_integrity(
    *,
    actor: str,
    session_data: Dict[str, Any],
) -> List[InsiderThreatSignal]:
    """Scan Redis-loaded session context for prompt injection patterns.

    Should be called in recommend.py before session context is fed to the
    agent orchestrator.  Returns a (possibly empty) list of signals.
    """
    signals: List[InsiderThreatSignal] = []
    for field_name, value in session_data.items():
        text = str(value) if not isinstance(value, (dict, list)) else json.dumps(value)
        for pat in _SESSION_INJECT_PATTERNS:
            if pat.search(text):
                sig = InsiderThreatSignal(
                    signal_type="session_context_injection",
                    actor=actor,
                    resource=f"session/{field_name}",
                    severity="critical",
                    context={
                        "field": field_name,
                        "pattern": pat.pattern,
                        "snippet": text[:200],
                    },
                )
                _emit(sig)
                signals.append(sig)
                break  # one signal per field is enough
    return signals
