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
from src.app.deps import get_redis
from src.app.models.db import get_engine


router = APIRouter(prefix="/api/v1/admin/incidents", tags=["admin", "escalation"])
public_router = APIRouter(prefix="/api/v1/incidents", tags=["incidents"])

_ROOM_SUBSCRIBERS: Dict[str, list[asyncio.Queue]] = {}
_CHAT_DIR = Path("tmp/incidents_chat")
_CHAT_DIR.mkdir(parents=True, exist_ok=True)

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
        r.setex(_token_key("buyer", incident_id), _TOKEN_TTL_SECONDS, buyer)
        r.setex(_token_key("staff", incident_id), _TOKEN_TTL_SECONDS, staff)
    except Exception:
        pass
    return {"buyer_token": buyer, "staff_token": staff, "ttl_seconds": _TOKEN_TTL_SECONDS}


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
        pass
    try:
        staff = r.get(_token_key("staff", incident_id))
        if staff and str(staff) == t:
            return ROLE_MERCHANT
    except Exception:
        pass
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
        pass

    # Publish to subscribers
    try:
        qs = list(_ROOM_SUBSCRIBERS.get(incident_id) or [])
        for q in qs:
            try:
                q.put_nowait(rec)
            except Exception:
                pass
    except Exception:
        pass


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


class EscalateRequest(BaseModel):
    case_id: str | None = None
    trace_id: str | None = None
    reason: str | None = None
    context: dict | None = None


@public_router.post("/escalate")
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
    # Seed a first assistant message so the room isn't empty.
    try:
        _append_chat(
            incident_id,
            role="assistant",
            message="Thanks. A support specialist has been notified and will review your case. You can add any extra details here.",
            meta={"source": "system", "case_id": body.case_id, "trace_id": body.trace_id},
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


@public_router.post("/{incident_id}/room/message")
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
