from __future__ import annotations

import json
import asyncio
import os
import uuid
import time
import base64
import hashlib
from typing import Dict
from pathlib import Path
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect, HTTPException, Header, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import text as sql_text

from src.app.security.auth import require_role, ROLE_DEVELOPER, ROLE_MERCHANT, ROLE_OWNER
from src.app.deps import get_redis, DummyRedis
import logging
from src.app.models.db import get_engine
from src.app.services.trace_contracts import validate_incident_matrix_gate
from src.app.schemas.ui_contracts import IncidentEscalateResponse, IncidentMessageResponse
from src.app.services.playbook_engine import (
    append_playbook_step,
    complete_playbook_run,
    execute_typed_actions,
    get_playbook_by_id,
    start_playbook_run,
)
from src.app.services.incident_alert_adapters import dispatch_incident_alert
from src.app.services.decision_log import log_trace_event


router = APIRouter(prefix="/api/v1/admin/incidents", tags=["admin", "escalation"])
public_router = APIRouter(prefix="/api/v1/incidents", tags=["incidents"])

_ROOM_SUBSCRIBERS: Dict[str, list[asyncio.Queue]] = {}
_CHAT_DIR = Path(str(os.getenv("INCIDENT_CHAT_DIR", "/tmp/incidents_chat") or "/tmp/incidents_chat"))
_CHAT_DIR.mkdir(parents=True, exist_ok=True)

_TOKENS_DIR = _CHAT_DIR / "tokens"
_TOKENS_DIR.mkdir(parents=True, exist_ok=True)

_TOKEN_TTL_SECONDS = int(os.getenv("INCIDENT_CHAT_TOKEN_TTL_SECONDS", "86400") or 86400)
_EVIDENCE_DIR = _CHAT_DIR / "evidence"
_EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)


def _is_local_demo_host(req: Request) -> bool:
    try:
        host = str((req.headers.get("host") or "")).lower()
        return host.startswith("127.0.0.1") or host.startswith("localhost")
    except Exception:
        return False


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_ts(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _ensure_incident_runtime_tables() -> None:
    try:
        eng = get_engine()
        with eng.begin() as conn:
            for stmt in [
                "ALTER TABLE incidents ADD COLUMN assigned_to TEXT",
                "ALTER TABLE incidents ADD COLUMN team TEXT",
                "ALTER TABLE incidents ADD COLUMN sla_status TEXT",
                "ALTER TABLE incidents ADD COLUMN sla_due_at TEXT",
                "ALTER TABLE incidents ADD COLUMN sla_breach_alerted_at TEXT",
                "ALTER TABLE incidents ADD COLUMN runbook_id TEXT",
                "ALTER TABLE incidents ADD COLUMN runbook_run_id TEXT",
                "ALTER TABLE incidents ADD COLUMN runbook_failure_alerted_at TEXT",
            ]:
                try:
                    conn.execute(sql_text(stmt))
                except Exception:
                    pass
            conn.execute(
                sql_text(
                    """
                    CREATE TABLE IF NOT EXISTS incident_evidence_attachments (
                      id TEXT PRIMARY KEY,
                      incident_id TEXT NOT NULL,
                      filename TEXT,
                      content_type TEXT,
                      file_path TEXT,
                      sha256 TEXT,
                      notes TEXT,
                      created_by TEXT,
                      created_at TEXT DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
            )
    except Exception:
        logging.getLogger(__name__).exception("failed ensuring escalation runtime tables")


def _allow_public_escalation(req: Request) -> bool:
    env = str(os.getenv("APP_ENV", "") or "").lower()
    explicit = str(os.getenv("ALLOW_UNAUTH_MERCHANT_DASHBOARD", "") or "").strip().lower()
    if explicit in ("1", "true", "yes", "on"):
        return _is_local_demo_host(req)
    if explicit in ("0", "false", "no", "off"):
        return False
    # If APP_ENV is unset, default to loopback-only allowance for local demos.
    if not env:
        return _is_local_demo_host(req)
    return env in ("local", "dev", "development") and _is_local_demo_host(req)


def _token_key(kind: str, incident_id: str) -> str:
    return f"incident_chat_token:{kind}:{incident_id}"


def _issue_tokens(incident_id: str) -> dict:
    buyer = str(uuid.uuid4())
    staff = str(uuid.uuid4())
    r = get_redis()
    try:
        if isinstance(r, DummyRedis):
            raise RuntimeError("using DummyRedis")
        r.setex(_token_key("buyer", incident_id), _TOKEN_TTL_SECONDS, buyer)
        r.setex(_token_key("staff", incident_id), _TOKEN_TTL_SECONDS, staff)
    except Exception:
        try:
            import time as _time
            import json as _json

            p = _TOKENS_DIR / f"{incident_id}.json"
            exp = int(_time.time()) + _TOKEN_TTL_SECONDS
            _json.dump({"buyer": buyer, "staff": staff, "exp": exp}, p.open("w", encoding="utf-8"))
            logging.getLogger("shopsquire.startup").warning("Redis unavailable; using file-backed tokens for incident %s", incident_id)
        except Exception:
            logging.getLogger(__name__).exception("failed to persist incident tokens to file")
    return {"buyer_token": buyer, "staff_token": staff, "ttl_seconds": _TOKEN_TTL_SECONDS}


def _issue_staff_token(incident_id: str) -> dict:
    """Issue/rotate a staff token for an incident without changing the buyer token."""
    staff = str(uuid.uuid4())
    r = get_redis()
    try:
        if isinstance(r, DummyRedis):
            raise RuntimeError("using DummyRedis")
        r.setex(_token_key("staff", incident_id), _TOKEN_TTL_SECONDS, staff)
    except Exception:
        try:
            import time as _time
            import json as _json

            p = _TOKENS_DIR / f"{incident_id}.json"
            data = {}
            if p.exists():
                try:
                    data = _json.loads(p.read_text(encoding="utf-8"))
                except Exception:
                    data = {}
            exp = int(_time.time()) + _TOKEN_TTL_SECONDS
            data.update({"staff": staff, "exp": exp})
            _json.dump(data, p.open("w", encoding="utf-8"))
            logging.getLogger("shopsquire.startup").warning("Redis unavailable; rotating file-backed staff token for %s", incident_id)
        except Exception:
            logging.getLogger(__name__).exception("failed to persist staff token to file")
    return {"staff_token": staff, "ttl_seconds": _TOKEN_TTL_SECONDS}


def _role_for_token(incident_id: str, token: str | None) -> str | None:
    if not token:
        return None
    t = str(token).strip()
    if not t:
        return None
    r = get_redis()
    try:
        buyer = r.get(_token_key("buyer", incident_id))
        if buyer and str(buyer) == t:
            return "buyer"
    except Exception:
        logging.getLogger(__name__).debug("redis get buyer token failed, falling back to file")
    try:
        staff = r.get(_token_key("staff", incident_id))
        if staff and str(staff) == t:
            return ROLE_MERCHANT
    except Exception:
        logging.getLogger(__name__).debug("redis get staff token failed, falling back to file")

    # File-backed fallback when Redis unavailable
    try:
        p = _TOKENS_DIR / f"{incident_id}.json"
        if p.exists():
            import json as _json, time as _time

            try:
                data = _json.loads(p.read_text(encoding="utf-8") or "{}")
            except Exception:
                data = {}
            exp = int(data.get("exp") or 0)
            if exp and exp < int(_time.time()):
                return None
            b = data.get("buyer")
            s = data.get("staff")
            if b and str(b) == t:
                return "buyer"
            if s and str(s) == t:
                return ROLE_MERCHANT
    except Exception:
        logging.getLogger(__name__).exception("file-backed token check failed")
    return None


def _require_public_token(incident_id: str, token: str | None) -> str:
    role = _role_for_token(incident_id, token)
    if not role:
        raise HTTPException(status_code=401, detail="invalid_or_missing_incident_token")
    return role


def _log_path(incident_id: str) -> Path:
    p = _CHAT_DIR / f"{incident_id}.ndjson"
    return p


def _append_chat(incident_id: str, role: str, message: str, meta: Dict | None = None) -> None:
    import time as _time
    rec = {
        "incident_id": incident_id,
        "role": role,
        "message": message,
        "meta": meta or {},
        # Use wall clock; avoid relying on an active asyncio loop in sync endpoints.
        "ts": int(_time.time() * 1000),
    }
    try:
        p = _log_path(incident_id)
        with p.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        logging.getLogger(__name__).exception("failed to append chat to disk for %s", incident_id)

    # Publish to subscribers
    try:
        qs = list(_ROOM_SUBSCRIBERS.get(incident_id) or [])
        for q in qs:
            try:
                q.put_nowait(rec)
            except Exception:
                logging.getLogger(__name__).exception("failed to publish chat to subscriber queue")
    except Exception:
        logging.getLogger(__name__).exception("failed to publish chat to subscribers for %s", incident_id)


def _incident_sla_minutes(severity: str | None) -> int:
    try:
        if str(severity or "").lower() in ("critical", "error", "high"):
            return int(os.getenv("INCIDENT_SLA_MINUTES_HIGH", "30") or 30)
        if str(severity or "").lower() in ("warn", "warning", "medium"):
            return int(os.getenv("INCIDENT_SLA_MINUTES_MEDIUM", "120") or 120)
        return int(os.getenv("INCIDENT_SLA_MINUTES_LOW", "240") or 240)
    except Exception:
        return 120


def _apply_sla_if_missing(incident_id: str) -> Dict:
    _ensure_incident_runtime_tables()
    eng = get_engine()
    now = _utc_now()
    with eng.begin() as conn:
        row = conn.execute(
            sql_text("SELECT severity, status, sla_due_at, sla_status FROM incidents WHERE id = :id LIMIT 1"),
            {"id": incident_id},
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="incident_not_found")
        severity = str(row[0] or "warn")
        status = str(row[1] or "open").lower()
        due_at_raw = row[2]
        sla_status = str(row[3] or "").lower()
        due_at = _parse_ts(str(due_at_raw) if due_at_raw else None)
        if due_at is None:
            due_at = now + timedelta(minutes=_incident_sla_minutes(severity))
            conn.execute(
                sql_text("UPDATE incidents SET sla_due_at = :due, sla_status = :st WHERE id = :id"),
                {"id": incident_id, "due": due_at.isoformat(), "st": "active"},
            )
            sla_status = "active"
        if status in ("resolved", "closed"):
            if sla_status != "met":
                conn.execute(
                    sql_text("UPDATE incidents SET sla_status = :st WHERE id = :id"),
                    {"id": incident_id, "st": "met"},
                )
            sla_status = "met"
        elif due_at < now and sla_status not in ("breached", "met"):
            conn.execute(
                sql_text("UPDATE incidents SET sla_status = :st WHERE id = :id"),
                {"id": incident_id, "st": "breached"},
            )
            sla_status = "breached"
    return {
        "incident_id": incident_id,
        "sla_due_at": due_at.isoformat() if due_at else None,
        "sla_status": sla_status or "active",
        "remaining_seconds": int((due_at - now).total_seconds()) if due_at else None,
    }


@router.get("")
@router.get("/")
def list_incidents(
    role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER])),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    status: str | None = Query(default=None),
    severity: str | None = Query(default=None),
) -> Dict:
    """List incidents for the escalation console."""
    _ = role
    try:
        _ensure_incident_runtime_tables()
        eng = get_engine()
        params: dict = {"lim": limit, "off": offset}
        if status:
            params["status"] = status
        else:
            params["status"] = None
        if severity:
            params["severity"] = severity
        else:
            params["severity"] = None
        with eng.begin() as conn:
            rows = conn.execute(
                sql_text(
                    "SELECT id, event_id, severity, title, status, created_at "
                    "FROM incidents "
                    "WHERE ((:status IS NULL AND status IN ('open', 'review')) OR status = :status) "
                    "AND (:severity IS NULL OR severity = :severity) "
                    "ORDER BY created_at DESC LIMIT :lim OFFSET :off"
                ),
                params,
            ).fetchall()
        incidents = [
            {
                "id": r[0],
                "event_id": r[1],
                "severity": r[2],
                "title": r[3],
                "status": r[4],
                "created_at": str(r[5]),
                "sla": _apply_sla_if_missing(str(r[0])),
            }
            for r in rows
        ]
        return {"incidents": incidents}
    except Exception:
        return {"incidents": []}


@router.get("/{incident_id}")
def get_incident(incident_id: str, role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER]))) -> Dict:
    """Return a single incident by ID."""
    _ = role
    try:
        _ensure_incident_runtime_tables()
        eng = get_engine()
        with eng.begin() as conn:
            row = conn.execute(
                sql_text(
                    "SELECT id, event_id, severity, title, description, status, created_at, created_by, assigned_to, team, sla_status, sla_due_at, runbook_id, runbook_run_id "
                    "FROM incidents WHERE id = :id LIMIT 1"
                ),
                {"id": incident_id},
            ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="incident_not_found")
        return {
            "id": row[0], "event_id": row[1], "severity": row[2], "title": row[3],
            "description": row[4], "status": row[5], "created_at": str(row[6]), "created_by": row[7],
            "assigned_to": row[8], "team": row[9],
            "sla_status": row[10], "sla_due_at": row[11],
            "runbook_id": row[12], "runbook_run_id": row[13],
            "sla": _apply_sla_if_missing(incident_id),
        }
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail="db_error")


@router.post("/{incident_id}/status")
def update_incident_status(
    incident_id: str,
    status: str = Query(...),
    role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict:
    """Update an incident's status (open/review/triaged/resolved)."""
    _ = role
    allowed = {"open", "review", "triaged", "resolved", "closed"}
    if status not in allowed:
        raise HTTPException(status_code=400, detail=f"status must be one of {allowed}")
    try:
        _ensure_incident_runtime_tables()
        eng = get_engine()
        with eng.begin() as conn:
            gate_enabled = str(os.getenv("INCIDENT_MATRIX_GATE_ENABLED", "1")).strip().lower() in ("1", "true", "yes", "on")
            if gate_enabled and status in {"resolved", "closed"}:
                gate = validate_incident_matrix_gate(conn, incident_id)
                if not gate.get("ok"):
                    raise HTTPException(
                        status_code=409,
                        detail={"error": "security_matrix_incomplete", "gate": gate},
                    )
            conn.execute(
                sql_text("UPDATE incidents SET status = :status, sla_status = CASE WHEN :status IN ('resolved', 'closed') THEN 'met' ELSE sla_status END WHERE id = :id"),
                {"status": status, "id": incident_id},
            )
        return {"ok": True, "incident_id": incident_id, "status": status, "sla": _apply_sla_if_missing(incident_id)}
    except Exception:
        raise HTTPException(status_code=500, detail="db_error")


@router.websocket("/{incident_id}/room/ws")
async def ws_room(incident_id: str, websocket: WebSocket):
    await websocket.accept()
    q: asyncio.Queue = asyncio.Queue()
    _ROOM_SUBSCRIBERS.setdefault(incident_id, []).append(q)
    try:
        # Send recent history snapshot (last 20 lines)
        try:
            p = _log_path(incident_id)
            if p.exists():
                lines = p.read_text(encoding="utf-8").splitlines()[-20:]
                await websocket.send_text(json.dumps([json.loads(l) for l in lines if l.strip()], ensure_ascii=False))
        except Exception:
            pass
        while True:
            if websocket.client_state.name != "CONNECTED":
                break
            try:
                rec = await q.get()
                await websocket.send_text(json.dumps([rec], ensure_ascii=False))
            except asyncio.CancelledError:
                break
            except Exception:
                await asyncio.sleep(0.2)
    except WebSocketDisconnect:
        return
    finally:
        try:
            subs = _ROOM_SUBSCRIBERS.get(incident_id) or []
            if q in subs:
                subs.remove(q)
        except Exception:
            pass


@router.get("/{incident_id}/room/stream")
async def sse_room(incident_id: str):
    q: asyncio.Queue = asyncio.Queue()
    _ROOM_SUBSCRIBERS.setdefault(incident_id, []).append(q)

    async def gen():
        # Snapshot
        try:
            p = _log_path(incident_id)
            if p.exists():
                lines = p.read_text(encoding="utf-8").splitlines()[-50:]
                yield "data: " + json.dumps([json.loads(l) for l in lines if l.strip()], ensure_ascii=False) + "\n\n"
        except Exception:
            pass
        try:
            while True:
                try:
                    rec = await q.get()
                    yield "data: " + json.dumps([rec], ensure_ascii=False) + "\n\n"
                except asyncio.CancelledError:
                    break
                except Exception:
                    await asyncio.sleep(0.25)
        finally:
            try:
                subs = _ROOM_SUBSCRIBERS.get(incident_id) or []
                if q in subs:
                    subs.remove(q)
            except Exception:
                pass

    return StreamingResponse(gen(), media_type="text/event-stream")


@router.post("/{incident_id}/room/message")
def send_message(incident_id: str, message: str, role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER]))) -> Dict:
    if not (message or "").strip():
        raise HTTPException(status_code=400, detail="message_required")
    try:
        _append_chat(incident_id, role, message, meta={"actor": role})
    except Exception:
        raise HTTPException(status_code=500, detail="append_failed")
    return {"sent": True}


@router.post("/{incident_id}/room/token")
def issue_staff_token(incident_id: str, role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER]))) -> Dict:
    """Create/rotate a staff token for the public SSE room (so EventSource can connect without headers)."""
    _ = role
    # Verify incident exists best-effort (demo is tolerant).
    try:
        eng = get_engine()
        with eng.begin() as conn:
            row = conn.execute(sql_text("SELECT id FROM incidents WHERE id = :id LIMIT 1"), {"id": incident_id}).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="incident_not_found")
    except HTTPException:
        raise
    except Exception:
        pass
    return {"ok": True, **_issue_staff_token(incident_id)}


class IncidentAssignRequest(BaseModel):
    assigned_to: str | None = None
    team: str | None = None


class IncidentSLARequest(BaseModel):
    minutes: int | None = None


class IncidentRunbookRequest(BaseModel):
    playbook_id: str
    context: dict | None = None
    tenant_id: str | None = None
    trace_id: str | None = None
    owner: str | None = None


class IncidentEvidenceRequest(BaseModel):
    filename: str
    content_type: str | None = None
    payload_b64: str | None = None
    notes: str | None = None
    external_url: str | None = None


@router.get("/ops/alerts/summary")
def incident_alert_summary(
    role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER])),
    hours: int = Query(default=24, ge=1, le=24 * 30),
    limit: int = Query(default=50, ge=1, le=500),
) -> Dict:
    _ = role
    _ensure_incident_runtime_tables()
    eng = get_engine()
    rows = []
    with eng.begin() as conn:
        rows = conn.execute(
            sql_text(
                "SELECT id, severity, title, status, created_at, sla_status, sla_due_at, "
                "sla_breach_alerted_at, runbook_id, runbook_run_id, runbook_failure_alerted_at "
                "FROM incidents "
                "WHERE sla_status = 'breached' OR sla_breach_alerted_at IS NOT NULL OR runbook_failure_alerted_at IS NOT NULL "
                "ORDER BY created_at DESC LIMIT :lim"
            ),
            {"lim": max(limit * 5, 200)},
        ).fetchall()

    now = _utc_now()
    window_sec = int(hours) * 3600
    sla_breach_total = 0
    runbook_failure_total = 0
    incident_ids = set()
    alerts: list[Dict] = []

    for r in rows or []:
        incident_id = str(r[0] or "")
        severity = str(r[1] or "warn")
        title = str(r[2] or "")
        status = str(r[3] or "open")
        created_at = str(r[4] or "")
        sla_status = str(r[5] or "")
        sla_due_at = str(r[6] or "") or None
        sla_alerted = _parse_ts(str(r[7] or "") or None)
        runbook_id = str(r[8] or "") or None
        runbook_run_id = str(r[9] or "") or None
        runbook_alerted = _parse_ts(str(r[10] or "") or None)

        if sla_alerted and int((now - sla_alerted).total_seconds()) <= window_sec:
            sla_breach_total += 1
            incident_ids.add(incident_id)
            alerts.append(
                {
                    "type": "sla_breach",
                    "incident_id": incident_id,
                    "severity": severity,
                    "title": title,
                    "status": status,
                    "alerted_at": sla_alerted.isoformat(),
                    "sla_due_at": sla_due_at,
                    "runbook_id": runbook_id,
                    "runbook_run_id": runbook_run_id,
                    "created_at": created_at,
                }
            )
        elif str(sla_status).lower() == "breached":
            # Backward-compat: treat unresolved breached incidents as active alerts
            due = _parse_ts(sla_due_at)
            if due and int((now - due).total_seconds()) <= window_sec:
                sla_breach_total += 1
                incident_ids.add(incident_id)
                alerts.append(
                    {
                        "type": "sla_breach",
                        "incident_id": incident_id,
                        "severity": severity,
                        "title": title,
                        "status": status,
                        "alerted_at": None,
                        "sla_due_at": sla_due_at,
                        "runbook_id": runbook_id,
                        "runbook_run_id": runbook_run_id,
                        "created_at": created_at,
                    }
                )

        if runbook_alerted and int((now - runbook_alerted).total_seconds()) <= window_sec:
            runbook_failure_total += 1
            incident_ids.add(incident_id)
            alerts.append(
                {
                    "type": "runbook_failure",
                    "incident_id": incident_id,
                    "severity": severity,
                    "title": title,
                    "status": status,
                    "alerted_at": runbook_alerted.isoformat(),
                    "sla_due_at": sla_due_at,
                    "runbook_id": runbook_id,
                    "runbook_run_id": runbook_run_id,
                    "created_at": created_at,
                }
            )

    alerts.sort(key=lambda x: str(x.get("alerted_at") or x.get("created_at") or ""), reverse=True)
    return {
        "hours": int(hours),
        "totals": {
            "sla_breach_alerts": sla_breach_total,
            "runbook_failure_alerts": runbook_failure_total,
            "incidents_with_alerts": len(incident_ids),
        },
        "recent": alerts[:limit],
    }


@router.post("/{incident_id}/assign")
def assign_incident(
    incident_id: str,
    body: IncidentAssignRequest,
    role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict:
    _ = role
    _ensure_incident_runtime_tables()
    eng = get_engine()
    with eng.begin() as conn:
        row = conn.execute(sql_text("SELECT id FROM incidents WHERE id = :id LIMIT 1"), {"id": incident_id}).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="incident_not_found")
        conn.execute(
            sql_text("UPDATE incidents SET assigned_to = :assigned_to, team = :team WHERE id = :id"),
            {"id": incident_id, "assigned_to": body.assigned_to, "team": body.team},
        )
    _append_chat(incident_id, "system", "Incident assignment updated.", meta={"assigned_to": body.assigned_to, "team": body.team})
    return {"ok": True, "incident_id": incident_id, "assigned_to": body.assigned_to, "team": body.team}


@router.post("/{incident_id}/sla/start")
def start_incident_sla(
    incident_id: str,
    body: IncidentSLARequest,
    role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict:
    _ = role
    _ensure_incident_runtime_tables()
    eng = get_engine()
    now = _utc_now()
    with eng.begin() as conn:
        row = conn.execute(sql_text("SELECT id, severity FROM incidents WHERE id = :id LIMIT 1"), {"id": incident_id}).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="incident_not_found")
        minutes = int(body.minutes or _incident_sla_minutes(str(row[1] or "warn")))
        due_at = now + timedelta(minutes=max(1, minutes))
        conn.execute(
            sql_text("UPDATE incidents SET sla_due_at = :due, sla_status = :st WHERE id = :id"),
            {"id": incident_id, "due": due_at.isoformat(), "st": "active"},
        )
    return {"ok": True, "incident_id": incident_id, "sla_due_at": due_at.isoformat(), "sla_status": "active"}


@router.get("/{incident_id}/sla")
def get_incident_sla(
    incident_id: str,
    role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict:
    _ = role
    return _apply_sla_if_missing(incident_id)


@router.post("/sla/scan")
def scan_incident_sla_breaches(
    role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict:
    _ = role
    _ensure_incident_runtime_tables()
    eng = get_engine()
    checked = 0
    breached = 0
    with eng.begin() as conn:
        rows = conn.execute(
            sql_text(
                "SELECT id, severity, title, description, status, sla_due_at, sla_breach_alerted_at "
                "FROM incidents WHERE status IN ('open', 'review', 'triaged') ORDER BY created_at DESC LIMIT 500"
            )
        ).fetchall()
    for row in rows or []:
        incident_id = str(row[0])
        severity = str(row[1] or "warn")
        title = str(row[2] or "")
        description = str(row[3] or "")
        status = str(row[4] or "open")
        due_at = str(row[5] or "") or None
        alerted = str(row[6] or "") or None
        checked += 1
        sla = _apply_sla_if_missing(incident_id)
        if str(sla.get("sla_status") or "").lower() == "breached":
            breached += 1
            _append_chat(incident_id, "system", "SLA breached for this incident.", meta={"sla": sla})
            if not alerted:
                out = dispatch_incident_alert(
                    "incident_sla_breached",
                    {
                        "id": incident_id,
                        "severity": severity,
                        "title": title,
                        "description": description,
                        "status": status,
                        "sla_due_at": due_at or sla.get("sla_due_at"),
                    },
                    details={"source": "manual_sla_scan"},
                )
                if bool(out.get("sent_total")):
                    try:
                        with eng.begin() as conn:
                            conn.execute(
                                sql_text("UPDATE incidents SET sla_breach_alerted_at = :ts WHERE id = :id"),
                                {"id": incident_id, "ts": _utc_now().isoformat()},
                            )
                    except Exception:
                        pass
                try:
                    log_trace_event(
                        trace_id=incident_id,
                        event_type="incident_alert_dispatch",
                        source_type="agent",
                        source_id="Escalation_Room",
                        target_type="system",
                        target_id=None,
                        payload={
                            "event_type": "incident_sla_breached",
                            "dispatch": out,
                            "incident_id": incident_id,
                        },
                    )
                except Exception:
                    pass
    return {"ok": True, "checked": checked, "breached": breached}


@router.post("/{incident_id}/runbook/execute")
def execute_incident_runbook(
    incident_id: str,
    body: IncidentRunbookRequest,
    role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict:
    _ = role
    _ensure_incident_runtime_tables()
    playbook = get_playbook_by_id(body.playbook_id)
    if not playbook:
        raise HTTPException(status_code=404, detail="playbook_not_found")
    trace_id = body.trace_id or f"incident:{incident_id}"
    run_id = start_playbook_run(
        trace_id=trace_id,
        decision_id=incident_id,
        tenant_id=body.tenant_id,
        playbook=playbook,
        owner=body.owner or "Escalation_Room",
        metadata={"incident_id": incident_id, "trigger": "manual_incident_runbook"},
    )
    if not run_id:
        raise HTTPException(status_code=500, detail="runbook_start_failed")
    actions = playbook.get("actions") if isinstance(playbook.get("actions"), list) else []
    append_playbook_step(run_id=run_id, event_type="incident_runbook_start", status="completed", evidence={"incident_id": incident_id})
    runbook_error = None
    try:
        result = execute_typed_actions(run_id=run_id, actions=actions, context=body.context or {"incident_id": incident_id})
    except Exception as exc:
        runbook_error = str(exc)
        result = {"ok": False, "failed": [{"error": str(exc)}], "completed": []}
    append_playbook_step(
        run_id=run_id,
        event_type="incident_runbook_actions",
        status="failed" if runbook_error else "completed",
        evidence=result,
    )
    final_status = "failed" if (runbook_error or result.get("failed")) else "completed"
    complete_playbook_run(run_id=run_id, status=final_status, outcome="incident_runbook_execution")
    eng = get_engine()
    incident_row = None
    with eng.begin() as conn:
        incident_row = conn.execute(
            sql_text("SELECT id, severity, title, description, status, runbook_failure_alerted_at FROM incidents WHERE id = :id LIMIT 1"),
            {"id": incident_id},
        ).fetchone()
        conn.execute(
            sql_text("UPDATE incidents SET runbook_id = :pid, runbook_run_id = :rid WHERE id = :id"),
            {"id": incident_id, "pid": body.playbook_id, "rid": run_id},
        )
        if final_status == "failed":
            already_alerted = str(incident_row[5] or "") if incident_row else ""
            if not already_alerted:
                out = dispatch_incident_alert(
                    "incident_runbook_failed",
                    {
                        "id": incident_id,
                        "severity": (str(incident_row[1] or "warn") if incident_row else "warn"),
                        "title": (str(incident_row[2] or "Runbook execution failed") if incident_row else "Runbook execution failed"),
                        "description": (str(incident_row[3] or "") if incident_row else ""),
                        "status": (str(incident_row[4] or "open") if incident_row else "open"),
                        "runbook_id": body.playbook_id,
                        "runbook_run_id": run_id,
                    },
                    details={"error": runbook_error, "failed": result.get("failed") if isinstance(result, dict) else []},
                )
                if bool(out.get("sent_total")):
                    conn.execute(
                        sql_text("UPDATE incidents SET runbook_failure_alerted_at = :ts WHERE id = :id"),
                        {"id": incident_id, "ts": _utc_now().isoformat()},
                    )
                try:
                    log_trace_event(
                        trace_id=incident_id,
                        event_type="incident_alert_dispatch",
                        source_type="agent",
                        source_id="Escalation_Room",
                        target_type="system",
                        target_id=None,
                        payload={
                            "event_type": "incident_runbook_failed",
                            "dispatch": out,
                            "incident_id": incident_id,
                            "runbook_id": body.playbook_id,
                            "run_id": run_id,
                        },
                    )
                except Exception:
                    pass
    _append_chat(incident_id, "system", "Runbook executed for incident.", meta={"playbook_id": body.playbook_id, "run_id": run_id, "status": final_status})
    return {"ok": True, "incident_id": incident_id, "playbook_id": body.playbook_id, "run_id": run_id, "result": result}


@router.post("/{incident_id}/evidence")
def attach_incident_evidence(
    incident_id: str,
    body: IncidentEvidenceRequest,
    role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict:
    _ensure_incident_runtime_tables()
    evidence_id = str(uuid.uuid4())
    incident_dir = _EVIDENCE_DIR / incident_id
    incident_dir.mkdir(parents=True, exist_ok=True)
    raw = b""
    if body.payload_b64:
        try:
            raw = base64.b64decode(body.payload_b64.encode("utf-8"), validate=False)
        except Exception:
            raw = b""
    sha = hashlib.sha256(raw).hexdigest() if raw else None
    path = incident_dir / f"{evidence_id}.bin"
    if raw:
        path.write_bytes(raw)
    stored_path = str(path) if raw else (body.external_url or "")
    eng = get_engine()
    with eng.begin() as conn:
        row = conn.execute(sql_text("SELECT id FROM incidents WHERE id = :id LIMIT 1"), {"id": incident_id}).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="incident_not_found")
        conn.execute(
            sql_text(
                """
                INSERT INTO incident_evidence_attachments (
                  id, incident_id, filename, content_type, file_path, sha256, notes, created_by, created_at
                ) VALUES (
                  :id, :incident_id, :filename, :content_type, :file_path, :sha256, :notes, :created_by, :created_at
                )
                """
            ),
            {
                "id": evidence_id,
                "incident_id": incident_id,
                "filename": body.filename,
                "content_type": body.content_type,
                "file_path": stored_path,
                "sha256": sha,
                "notes": body.notes,
                "created_by": role,
                "created_at": _utc_now().isoformat(),
            },
        )
    _append_chat(incident_id, "system", "Evidence attached to incident.", meta={"evidence_id": evidence_id, "filename": body.filename})
    return {"ok": True, "incident_id": incident_id, "evidence_id": evidence_id, "sha256": sha, "file_path": stored_path}


@router.get("/{incident_id}/evidence")
def list_incident_evidence(
    incident_id: str,
    role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict:
    _ = role
    _ensure_incident_runtime_tables()
    eng = get_engine()
    with eng.begin() as conn:
        rows = conn.execute(
            sql_text(
                "SELECT id, filename, content_type, file_path, sha256, notes, created_by, created_at "
                "FROM incident_evidence_attachments WHERE incident_id = :id ORDER BY created_at DESC LIMIT 200"
            ),
            {"id": incident_id},
        ).fetchall()
    return {
        "incident_id": incident_id,
        "items": [
            {
                "id": r[0],
                "filename": r[1],
                "content_type": r[2],
                "file_path": r[3],
                "sha256": r[4],
                "notes": r[5],
                "created_by": r[6],
                "created_at": str(r[7]),
            }
            for r in rows or []
        ],
    }


class EscalateRequest(BaseModel):
    case_id: str | None = None
    trace_id: str | None = None
    reason: str | None = None
    context: dict | None = None


@public_router.post("/escalate", response_model=IncidentEscalateResponse)
def public_escalate(body: EscalateRequest, request: Request) -> Dict:
    """Create an incident + issue buyer/staff chat tokens (local-dev demo only).

    In production this should be bound to an authenticated user session.
    """
    if not _allow_public_escalation(request):
        raise HTTPException(status_code=403, detail="public_escalation_disabled")
    incident_id = str(uuid.uuid4())
    event_id = (body.case_id or body.trace_id or f"public-{incident_id}")[:64]
    title = "Buyer escalation: human review requested"
    desc = {
        "reason": body.reason or "human_review_requested",
        "case_id": body.case_id,
        "trace_id": body.trace_id,
        "context": body.context or {},
    }
    try:
        _ensure_incident_runtime_tables()
        eng = get_engine()
        with eng.begin() as conn:
            conn.execute(
                sql_text(
                    "INSERT INTO incidents (id, event_id, created_by, severity, title, description, status, sla_status, sla_due_at) "
                    "VALUES (:id, :event_id, :created_by, :severity, :title, :description, :status, :sla_status, :sla_due_at)"
                ),
                {
                    "id": incident_id,
                    "event_id": event_id,
                    "created_by": "buyer",
                    "severity": "warn",
                    "title": title,
                    "description": json.dumps(desc, ensure_ascii=False),
                    "status": "open",
                    "sla_status": "active",
                    "sla_due_at": (_utc_now() + timedelta(minutes=_incident_sla_minutes("warn"))).isoformat(),
                },
            )
    except Exception:
        # Incident table exists in Postgres; ignore failures in local demo mode.
        pass
    toks = _issue_tokens(incident_id)
    # Seed a first assistant message with context so staff can join with immediate triage facts.
    try:
        trace_ctx = {}
        if isinstance(body.context, dict):
            t = body.context.get("trace")
            if isinstance(t, dict):
                trace_ctx = t
        ctx_case = trace_ctx.get("case_id") or body.case_id
        ctx_trace = trace_ctx.get("trace_id") or body.trace_id
        ctx_sev = trace_ctx.get("severity")
        ctx_findings = trace_ctx.get("findings") if isinstance(trace_ctx.get("findings"), list) else []
        summary_bits = []
        if ctx_case:
            summary_bits.append(f"Case: {ctx_case}")
        if ctx_trace:
            summary_bits.append(f"Trace: {ctx_trace}")
        if ctx_sev:
            summary_bits.append(f"Severity: {ctx_sev}")
        if ctx_findings:
            summary_bits.append(f"Findings: {', '.join([str(x) for x in ctx_findings[:6]])}")
        seed_msg = "Thanks. A support specialist has been notified and will review your case."
        if summary_bits:
            seed_msg = seed_msg + "\n\nEscalation context:\n" + "\n".join(summary_bits)
        seed_msg = seed_msg + "\n\nYou can add any extra details here."
        _append_chat(
            incident_id,
            role="assistant",
            message=seed_msg,
            meta={
                "source": "system",
                "case_id": body.case_id,
                "trace_id": body.trace_id,
                "trace_context": trace_ctx,
            },
        )
    except Exception:
        pass
    return {"ok": True, "incident_id": incident_id, **toks}


class PublicChatMessage(BaseModel):
    message: str


@public_router.get("/{incident_id}/room/stream")
async def public_sse_room(
    incident_id: str,
    request: Request,
    token: str | None = Query(default=None),
    x_incident_token: str | None = Header(default=None, alias="x-incident-token"),
):
    _ = request  # reserved for future ABAC/telemetry
    _require_public_token(incident_id, token or x_incident_token)

    q: asyncio.Queue = asyncio.Queue()
    _ROOM_SUBSCRIBERS.setdefault(incident_id, []).append(q)

    async def gen():
        # Snapshot
        try:
            p = _log_path(incident_id)
            if p.exists():
                lines = p.read_text(encoding="utf-8").splitlines()[-50:]
                yield "data: " + json.dumps([json.loads(l) for l in lines if l.strip()], ensure_ascii=False) + "\n\n"
        except Exception:
            pass
        try:
            while True:
                try:
                    rec = await q.get()
                    yield "data: " + json.dumps([rec], ensure_ascii=False) + "\n\n"
                except asyncio.CancelledError:
                    break
                except Exception:
                    await asyncio.sleep(0.25)
        finally:
            try:
                subs = _ROOM_SUBSCRIBERS.get(incident_id) or []
                if q in subs:
                    subs.remove(q)
            except Exception:
                pass

    return StreamingResponse(gen(), media_type="text/event-stream")


@public_router.post("/{incident_id}/room/message", response_model=IncidentMessageResponse)
def public_send_message(
    incident_id: str,
    body: PublicChatMessage,
    token: str | None = Query(default=None),
    x_incident_token: str | None = Header(default=None, alias="x-incident-token"),
) -> Dict:
    role = _require_public_token(incident_id, token or x_incident_token)
    msg = str(getattr(body, "message", "") or "")
    if not msg.strip():
        raise HTTPException(status_code=400, detail="message_required")
    try:
        _append_chat(incident_id, role, msg.strip(), meta={"actor": role, "channel": "public"})
    except Exception:
        raise HTTPException(status_code=500, detail="append_failed")
    return {"sent": True, "role": role}
