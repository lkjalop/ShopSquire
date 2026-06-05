from __future__ import annotations

import json
import os
import smtplib
from datetime import datetime, timezone
from email.message import EmailMessage
from typing import Any, Dict, List

from src.app.security.url_guard import ensure_safe_outbound_url

try:
    import httpx as _httpx
except Exception:  # pragma: no cover
    _httpx = None  # type: ignore[assignment]


def _enabled() -> bool:
    raw = str(os.getenv("INCIDENT_ALERTS_ENABLED", "1") or "1").strip().lower()
    return raw in ("1", "true", "yes", "on")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _incident_console_base() -> str:
    base = str(
        os.getenv("ADMIN_CONSOLE_BASE_URL", os.getenv("SHOPSQUIRE_ADMIN_BASE_URL", "http://localhost:5173/admin"))
        or "http://localhost:5173/admin"
    ).rstrip("/")
    return base


def _incident_link(incident_id: str) -> str:
    return f"{_incident_console_base()}?tab=escalations&incident={incident_id}"


def _render_summary(event_type: str, incident: Dict[str, Any], details: Dict[str, Any] | None = None) -> Dict[str, Any]:
    d = details if isinstance(details, dict) else {}
    iid = str(incident.get("id") or "")
    severity = str(incident.get("severity") or "warn")
    title = str(incident.get("title") or "Incident escalation")
    status = str(incident.get("status") or "open")
    description = str(incident.get("description") or "")
    runbook_id = str(incident.get("runbook_id") or "")
    run_id = str(incident.get("runbook_run_id") or "")
    sla_due_at = str(incident.get("sla_due_at") or "")
    summary = {
        "event_type": event_type,
        "incident_id": iid,
        "severity": severity,
        "title": title,
        "status": status,
        "description": description[:500],
        "sla_due_at": sla_due_at or None,
        "runbook_id": runbook_id or None,
        "runbook_run_id": run_id or None,
        "details": d,
        "link": _incident_link(iid),
        "timestamp": _utc_now_iso(),
    }
    return summary


def _slack_webhooks() -> List[str]:
    out: List[str] = []
    one = str(os.getenv("INCIDENT_ALERT_SLACK_WEBHOOK_URL", "") or "").strip()
    if one:
        out.append(one)
    many = str(os.getenv("INCIDENT_ALERT_SLACK_WEBHOOK_URLS", "") or "").strip()
    if many:
        for item in many.split(","):
            v = str(item or "").strip()
            if v:
                out.append(v)
    # de-dupe, preserve order
    dedup: List[str] = []
    seen = set()
    for u in out:
        if u not in seen:
            seen.add(u)
            dedup.append(u)
    return dedup


def _pagerduty_routing_key() -> str:
    return str(os.getenv("INCIDENT_ALERT_PAGERDUTY_ROUTING_KEY", "") or "").strip()


def _pagerduty_events_url() -> str:
    return str(os.getenv("INCIDENT_ALERT_PAGERDUTY_EVENTS_URL", "https://events.pagerduty.com/v2/enqueue") or "").strip()


def _email_recipients() -> List[str]:
    raw = str(os.getenv("INCIDENT_ALERT_EMAIL_TO", "") or "").strip()
    if not raw:
        return []
    out = [x.strip() for x in raw.split(",") if str(x or "").strip()]
    # de-dupe, preserve order
    dedup: List[str] = []
    seen = set()
    for e in out:
        if e.lower() not in seen:
            seen.add(e.lower())
            dedup.append(e)
    return dedup


def _http_post(url: str, payload: Dict[str, Any], timeout: float = 8.0) -> int:
    """Sync HTTP POST using httpx (same API as requests, non-blocking-event-loop safe).

    Called from threads or asyncio.to_thread() — never called directly from async handlers.
    Returns HTTP status code, or 0 on failure.
    """
    if _httpx is None:
        return 0
    try:
        with _httpx.Client(timeout=timeout) as client:
            resp = client.post(url, json=payload)
            return int(resp.status_code)
    except Exception:
        return 0


def _send_slack(summary: Dict[str, Any]) -> Dict[str, Any]:
    urls = _slack_webhooks()
    if not urls:
        return {"enabled": False, "sent": 0, "errors": []}
    if _httpx is None:
        return {"enabled": True, "sent": 0, "errors": ["httpx_unavailable"]}
    sent = 0
    errors: List[str] = []
    text = (
        f"[{summary.get('event_type')}] {summary.get('severity')} "
        f"incident={summary.get('incident_id')} status={summary.get('status')} "
        f"title={summary.get('title')} link={summary.get('link')}"
    )
    payload = {"text": text, "attachments": [{"color": "#d9534f", "text": json.dumps(summary, ensure_ascii=False)}]}
    for url in urls:
        try:
            ensure_safe_outbound_url(url)
            status = _http_post(url, payload, timeout=8.0)
            if 200 <= status < 300:
                sent += 1
            else:
                errors.append(f"status_{status}")
        except Exception as exc:
            errors.append(str(exc))
    return {"enabled": True, "sent": sent, "errors": errors}


def _send_pagerduty(summary: Dict[str, Any]) -> Dict[str, Any]:
    routing_key = _pagerduty_routing_key()
    if not routing_key:
        return {"enabled": False, "sent": 0, "errors": []}
    if _httpx is None:
        return {"enabled": True, "sent": 0, "errors": ["httpx_unavailable"]}
    url = _pagerduty_events_url()
    payload = {
        "routing_key": routing_key,
        "event_action": "trigger",
        "payload": {
            "summary": f"{summary.get('event_type')} - incident {summary.get('incident_id')}",
            "source": "shopsquire-escalation-room",
            "severity": "critical" if str(summary.get("severity", "")).lower() in ("critical", "high", "error") else "warning",
            "custom_details": summary,
        },
        "links": [{"href": summary.get("link"), "text": "Escalation Console"}],
    }
    try:
        ensure_safe_outbound_url(url)
        status = _http_post(url, payload, timeout=8.0)
        if 200 <= status < 300:
            return {"enabled": True, "sent": 1, "errors": []}
        return {"enabled": True, "sent": 0, "errors": [f"status_{status}"]}
    except Exception as exc:
        return {"enabled": True, "sent": 0, "errors": [str(exc)]}


def _send_email(summary: Dict[str, Any]) -> Dict[str, Any]:
    recipients = _email_recipients()
    if not recipients:
        return {"enabled": False, "sent": 0, "errors": []}
    host = str(os.getenv("SMTP_HOST", "") or "").strip()
    if not host:
        return {"enabled": True, "sent": 0, "errors": ["smtp_not_configured"]}
    port = int(str(os.getenv("SMTP_PORT", "587") or "587") or 587)
    user = str(os.getenv("SMTP_USER", "") or "").strip()
    password = str(os.getenv("SMTP_PASSWORD", "") or "").strip()
    sender = str(os.getenv("SMTP_SENDER", user or "noreply@shopsquire.local") or (user or "noreply@shopsquire.local"))
    subject = f"[ShopSquire] {summary.get('event_type')} - incident {summary.get('incident_id')}"
    body = json.dumps(summary, ensure_ascii=False, indent=2)
    sent = 0
    errors: List[str] = []
    for to in recipients:
        try:
            msg = EmailMessage()
            msg["From"] = sender
            msg["To"] = to
            msg["Subject"] = subject
            msg.set_content(body)
            with smtplib.SMTP(host, port, timeout=15) as smtp:
                smtp.starttls()
                if user and password:
                    smtp.login(user, password)
                smtp.send_message(msg)
            sent += 1
        except Exception as exc:
            errors.append(str(exc))
    return {"enabled": True, "sent": sent, "errors": errors}


def dispatch_incident_alert(event_type: str, incident: Dict[str, Any], details: Dict[str, Any] | None = None) -> Dict[str, Any]:
    if not _enabled():
        return {"ok": False, "disabled": True, "channels": {}}
    summary = _render_summary(event_type=event_type, incident=incident or {}, details=details or {})
    slack = _send_slack(summary)
    pagerduty = _send_pagerduty(summary)
    email = _send_email(summary)
    total_sent = int(slack.get("sent") or 0) + int(pagerduty.get("sent") or 0) + int(email.get("sent") or 0)
    return {
        "ok": total_sent > 0,
        "disabled": False,
        "summary": summary,
        "channels": {
            "slack": slack,
            "pagerduty": pagerduty,
            "email": email,
        },
        "sent_total": total_sent,
    }
