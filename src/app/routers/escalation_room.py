from __future__ import annotations

import json
import asyncio
import os
import uuid
from typing import Dict
from pathlib import Path

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


router = APIRouter(prefix="/api/v1/admin/incidents", tags=["admin", "escalation"])
public_router = APIRouter(prefix="/api/v1/incidents", tags=["incidents"])

_ROOM_SUBSCRIBERS: Dict[str, list[asyncio.Queue]] = {}
_CHAT_DIR = Path("tmp/incidents_chat")
_CHAT_DIR.mkdir(parents=True, exist_ok=True)

_TOKENS_DIR = _CHAT_DIR / "tokens"
_TOKENS_DIR.mkdir(parents=True, exist_ok=True)

_TOKEN_TTL_SECONDS = int(os.getenv("INCIDENT_CHAT_TOKEN_TTL_SECONDS", "86400") or 86400)


def _is_local_demo_host(req: Request) -> bool:
    try:
        host = str((req.headers.get("host") or "")).lower()
        return host.startswith("127.0.0.1") or host.startswith("localhost")
    except Exception:
        return False


def _allow_public_escalation(req: Request) -> bool:
    env = str(os.getenv("APP_ENV", "") or "").lower()
    explicit = str(os.getenv("ALLOW_UNAUTH_MERCHANT_DASHBOARD", "") or "").strip().lower()
    if explicit in ("1", "true", "yes", "on"):
        return _is_local_demo_host(req)
    if explicit in ("0", "false", "no", "off"):
        return False
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
        eng = get_engine()
        clauses = []
        params: dict = {"lim": limit, "off": offset}
        if status:
            clauses.append("status = :status")
            params["status"] = status
        else:
            clauses.append("status IN ('open', 'review')")
        if severity:
            clauses.append("severity = :severity")
            params["severity"] = severity
        where = " AND ".join(clauses) if clauses else "1=1"
        with eng.begin() as conn:
            rows = conn.execute(
                sql_text(
                    f"SELECT id, event_id, severity, title, status, created_at "
                    f"FROM incidents WHERE {where} "
                    f"ORDER BY created_at DESC LIMIT :lim OFFSET :off"
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
        eng = get_engine()
        with eng.begin() as conn:
            row = conn.execute(
                sql_text(
                    "SELECT id, event_id, severity, title, description, status, created_at, created_by "
                    "FROM incidents WHERE id = :id LIMIT 1"
                ),
                {"id": incident_id},
            ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="incident_not_found")
        return {
            "id": row[0], "event_id": row[1], "severity": row[2], "title": row[3],
            "description": row[4], "status": row[5], "created_at": str(row[6]), "created_by": row[7],
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
                sql_text("UPDATE incidents SET status = :status WHERE id = :id"),
                {"status": status, "id": incident_id},
            )
        return {"ok": True, "incident_id": incident_id, "status": status}
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
        eng = get_engine()
        with eng.begin() as conn:
            conn.execute(
                sql_text(
                    "INSERT INTO incidents (id, event_id, created_by, severity, title, description, status) "
                    "VALUES (:id, :event_id, :created_by, :severity, :title, :description, :status)"
                ),
                {
                    "id": incident_id,
                    "event_id": event_id,
                    "created_by": "buyer",
                    "severity": "warn",
                    "title": title,
                    "description": json.dumps(desc, ensure_ascii=False),
                    "status": "open",
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
