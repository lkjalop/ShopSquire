from __future__ import annotations

import json
import asyncio
from typing import Dict
from pathlib import Path

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import StreamingResponse

from src.app.security.auth import require_role, ROLE_DEVELOPER, ROLE_MERCHANT, ROLE_OWNER


router = APIRouter(prefix="/api/v1/admin/incidents", tags=["admin", "escalation"])

_ROOM_SUBSCRIBERS: Dict[str, list[asyncio.Queue]] = {}
_CHAT_DIR = Path("tmp/incidents_chat")
_CHAT_DIR.mkdir(parents=True, exist_ok=True)


def _log_path(incident_id: str) -> Path:
    p = _CHAT_DIR / f"{incident_id}.ndjson"
    return p


def _append_chat(incident_id: str, role: str, message: str, meta: Dict | None = None) -> None:
    rec = {
        "incident_id": incident_id,
        "role": role,
        "message": message,
        "meta": meta or {},
        "ts": int(asyncio.get_event_loop().time() * 1000),
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
