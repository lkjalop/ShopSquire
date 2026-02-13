from fastapi import APIRouter, HTTPException, Request, Depends
from typing import List, Dict, Any, Optional
from datetime import datetime
import json
import uuid

from src.app.models.db import db_session
from src.app.models.decision_trace_events import ensure_decision_trace_events_table
from src.app.deps import security_sanitize
from src.app.security.auth import require_role, ROLE_DEVELOPER, ROLE_MERCHANT, ROLE_OWNER
from src.app.services.trace_broker import publish as publish_trace
from src.app.services.decision_log import get_cached_trace_events
import asyncio
from src.app.services.db_read_routing import read_session
from src.app.services.dependency_resilience import call_with_resilience
from src.app.services.trace_taxonomy import normalize_trace_event_type

router = APIRouter(prefix="/api/v1/trace", tags=["decision-trace"])


@router.post("/events")
def append_trace_events(events: List[Dict[str, Any]], role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER]))):
    """Append one or more trace events to `decision_trace_events`.

    Expected event shape: { trace_id, event_type, source_type, source_id?, target_type?, target_id?, payload }
    """
    if not events:
        raise HTTPException(status_code=400, detail="no_events")
    stored = 0
    now_iso = datetime.utcnow().isoformat()
    try:
        ensure_decision_trace_events_table()
    except Exception:
        pass
    try:
        with db_session() as db:
            for ev in events:
                trace_id = ev.get("trace_id")
                if not trace_id:
                    continue
                # Compute per-trace sequencing
                try:
                    next_seq_row = db.execute(
                        "SELECT COALESCE(MAX(seq), 0) + 1 FROM decision_trace_events WHERE trace_id = :tid",
                        {"tid": trace_id},
                    ).fetchone()
                    next_seq = int(next_seq_row[0]) if next_seq_row and next_seq_row[0] is not None else 1
                except Exception:
                    next_seq = None
                # Stable ID default: trace_id:seq when available, else UUID4
                evt_id = ev.get("id") or (f"{trace_id}:{next_seq}" if next_seq is not None else str(uuid.uuid4()))
                payload = ev.get("payload") or {}
                payload = security_sanitize(payload) if isinstance(payload, dict) else payload
                canonical_type, original_type = normalize_trace_event_type(ev.get("event_type") or ev.get("type"))
                if isinstance(payload, dict):
                    payload.setdefault("_event_type", canonical_type)
                    payload.setdefault("_schema_version", "1.0")
                    if original_type:
                        payload.setdefault("_original_event_type", original_type)
                db.execute(
                    "INSERT INTO decision_trace_events (id, seq, trace_id, event_type, source_type, source_id, target_type, target_id, payload, created_at) VALUES (:id, :seq, :trace_id, :event_type, :source_type, :source_id, :target_type, :target_id, :payload, :created_at)",
                    {
                        "id": evt_id,
                        "seq": ev.get("seq") if isinstance(ev.get("seq"), int) else next_seq,
                        "trace_id": trace_id,
                        "event_type": canonical_type,
                        "source_type": ev.get("source_type") or "user",
                        "source_id": ev.get("source_id"),
                        "target_type": ev.get("target_type"),
                        "target_id": ev.get("target_id"),
                        "payload": json.dumps(payload, ensure_ascii=False),
                        "created_at": ev.get("created_at") or now_iso,
                    },
                )
                stored += 1
            db.commit()
            # publish events to in-process subscribers (best-effort)
            try:
                loop = asyncio.get_event_loop()
                for ev in events:
                    try:
                        # publish asynchronously without awaiting
                        loop.create_task(publish_trace(ev.get("trace_id"), {
                            "id": ev.get("id") or (f"{ev.get('trace_id')}:{ev.get('seq')}") ,
                            "seq": ev.get('seq'),
                            "trace_id": ev.get('trace_id'),
                            "event_type": normalize_trace_event_type(ev.get('event_type') or ev.get('type'))[0],
                            "source_type": ev.get('source_type') or 'user',
                            "source_id": ev.get('source_id'),
                            "target_type": ev.get('target_type'),
                            "target_id": ev.get('target_id'),
                            "payload": ev.get('payload') or {},
                            "created_at": ev.get('created_at') or None,
                        }))
                    except Exception:
                        pass
            except Exception:
                pass
    except Exception:
        raise HTTPException(status_code=500, detail="persist_failed")
    try:
        print(f"[append_trace_events] stored={stored}")
    except Exception:
        pass
    return {"stored": stored}


@router.get("/{trace_id}/events/stream")
async def stream_trace_events(trace_id: str, request: Request):
    """SSE stream for decision trace events for the given trace_id."""
    from starlette.responses import StreamingResponse

    q = subscribe = None
    try:
        from src.app.services.trace_broker import subscribe as _sub, unsubscribe as _unsub
        q = _sub(trace_id)
    except Exception:
        q = None

    async def event_gen():
        # initial: emit existing events snapshot (best-effort)
        try:
            with read_session(read_class="timeline") as db:
                try:
                        from src.app.models.db import db_session as _db_session
                        with _db_session() as dbs:
                            rows = dbs.execute(
                                "SELECT id, seq, trace_id, event_type, source_type, source_id, target_type, target_id, payload, created_at FROM decision_trace_events WHERE trace_id = :trace_id ORDER BY CASE WHEN seq IS NULL THEN 1 ELSE 0 END, seq ASC, created_at ASC",
                                {"trace_id": trace_id},
                            ).fetchall()
                except Exception:
                    rows = []
            items = []
            for r in rows or []:
                try:
                    payload = json.loads(r[8]) if isinstance(r[8], str) else r[8]
                except Exception:
                    payload = r[8]
                items.append({
                    "id": r[0],
                    "seq": r[1],
                    "trace_id": r[2],
                    "event_type": r[3],
                    "source_type": r[4],
                    "source_id": r[5],
                    "target_type": r[6],
                    "target_id": r[7],
                    "payload": payload,
                    "created_at": r[9],
                })
            # Always emit a first snapshot so clients/tests don't block waiting
            # for the initial event chunk.
            if not items:
                try:
                    items = get_cached_trace_events(trace_id)
                except Exception:
                    items = []
            yield f"data: {json.dumps(items, ensure_ascii=False)}\n\n"
        except Exception:
            pass

        # stream new events from broker
        if q is None:
            # fallback: poll DB if no broker
            last = None
            while True:
                if await request.is_disconnected():
                    break
                try:
                    with read_session(read_class="timeline") as db:
                        try:
                                from src.app.models.db import db_session as _db_session
                                with _db_session() as dbs:
                                    rows = dbs.execute(
                                        "SELECT id, seq, trace_id, event_type, source_type, source_id, target_type, target_id, payload, created_at FROM decision_trace_events WHERE trace_id = :trace_id AND created_at > :since ORDER BY created_at ASC",
                                        {"trace_id": trace_id, "since": last or '1970-01-01T00:00:00Z'},
                                    ).fetchall()
                        except Exception:
                            rows = []
                    items = []
                    for r in rows or []:
                        try:
                            payload = json.loads(r[8]) if isinstance(r[8], str) else r[8]
                        except Exception:
                            payload = r[8]
                        items.append({
                            "id": r[0],
                            "seq": r[1],
                            "trace_id": r[2],
                            "event_type": r[3],
                            "source_type": r[4],
                            "source_id": r[5],
                            "target_type": r[6],
                            "target_id": r[7],
                            "payload": payload,
                            "created_at": r[9],
                        })
                        last = r[9]
                    if items:
                        yield f"data: {json.dumps(items, ensure_ascii=False)}\n\n"
                except Exception:
                    pass
                await asyncio.sleep(1.0)
        else:
            try:
                while True:
                    if await request.is_disconnected():
                        break
                    try:
                        ev = await q.get()
                        yield f"data: {json.dumps([ev], ensure_ascii=False)}\n\n"
                    except asyncio.CancelledError:
                        break
                    except Exception:
                        await asyncio.sleep(0.2)
            finally:
                try:
                    from src.app.services.trace_broker import unsubscribe as _un
                    _un(trace_id, q)
                except Exception:
                    pass

    return StreamingResponse(event_gen(), media_type="text/event-stream")


@router.get("/{trace_id}/events")
def list_trace_events(trace_id: str):
    try:
        from src.app.models.db import db_session as _db_session
        with _db_session() as db:
            try:
                rows = db.execute(
                    "SELECT id, seq, trace_id, event_type, source_type, source_id, target_type, target_id, payload, created_at FROM decision_trace_events WHERE trace_id = :trace_id ORDER BY CASE WHEN seq IS NULL THEN 1 ELSE 0 END, seq ASC, created_at ASC",
                    {"trace_id": trace_id},
                ).fetchall()
            except Exception:
                rows = []
        out = []
        for r in rows or []:
            # r indexes: 0:id,1:seq,2:trace_id,3:event_type,4:source_type,5:source_id,6:target_type,7:target_id,8:payload,9:created_at
            raw_payload = r[8]
            try:
                payload = json.loads(raw_payload) if isinstance(raw_payload, str) else (raw_payload or {})
            except Exception:
                payload = {}

            out.append({
                "id": r[0],
                "seq": r[1],
                "trace_id": r[2],
                "event_type": r[3],
                "source_type": r[4],
                "source_id": r[5],
                "target_type": r[6],
                "target_id": r[7],
                "payload": payload,
                "created_at": r[9],
            })
        if not out:
            try:
                out = get_cached_trace_events(trace_id)
            except Exception:
                out = []
        return {"events": out}
    except Exception:
        raise HTTPException(status_code=500, detail="fetch_failed")


@router.get("/{trace_id}/timeline")
def get_decision_timeline(trace_id: str):
    """Lightweight timeline with summary stats for decision trace panel.

    This endpoint is defensive: it tolerates malformed payloads and extracts
    latency and display tags safely.
    """
    try:
        from src.app.models.db import db_session as _db_session
        with _db_session() as db:
            try:
                rows = db.execute(
                    "SELECT id, seq, event_type, source_type, source_id, target_type, target_id, payload, created_at FROM decision_trace_events WHERE trace_id = :trace_id ORDER BY CASE WHEN seq IS NULL THEN 1 ELSE 0 END, seq ASC, created_at ASC",
                    {"trace_id": trace_id},
                ).fetchall()
            except Exception:
                rows = []
        # Summaries
        summary = {
            "total_events": 0,
            "rule_matches": 0,
            "tool_calls": 0,
            "model_invokes": 0,
            "escalations": 0,
            "total_latency_ms": 0,
        }

        events: list[dict] = []
        for r in rows or []:
            # r indexes: 0:id,1:seq,2:event_type,3:source_type,4:source_id,5:target_type,6:target_id,7:payload,8:created_at
            summary["total_events"] += 1
            evt_type = r[2] or "event"
            if evt_type == "rule_match":
                summary["rule_matches"] += 1
            elif evt_type == "tool_call":
                summary["tool_calls"] += 1
            elif evt_type == "model_invoke":
                summary["model_invokes"] += 1
            elif evt_type == "escalation":
                summary["escalations"] += 1

            # Defensive payload parsing
            raw_payload = r[7]
            try:
                payload = json.loads(raw_payload) if isinstance(raw_payload, str) else (raw_payload or {})
            except Exception:
                payload = {}

            # Extract latency safely (accept int, float, or numeric string)
            lat: Optional[int] = None
            try:
                if isinstance(payload, dict) and payload.get("latency_ms") is not None:
                    v = payload.get("latency_ms")
                    if isinstance(v, (int, float)):
                        lat = int(v)
                    else:
                        # attempt numeric parse from string
                        try:
                            lat = int(float(str(v)))
                        except Exception:
                            lat = None
            except Exception:
                lat = None

            if isinstance(lat, int):
                summary["total_latency_ms"] += lat

            # Compute tags via helper to keep logic consistent and testable
            def extract_tags(payload_obj: Any) -> List[str]:
                tags_local: List[str] = []
                if not isinstance(payload_obj, dict):
                    return tags_local
                t = payload_obj.get("tier")
                if t is not None:
                    try:
                        tags_local.append(f"T{int(t)}")
                    except Exception:
                        tags_local.append(f"T{str(t)}")
                if payload_obj.get("cached"):
                    tags_local.append("CACHED")
                if payload_obj.get("rule_id"):
                    tags_local.append(str(payload_obj.get("rule_id")))
                if payload_obj.get("model"):
                    try:
                        tags_local.append(str(payload_obj.get("model"))[:10])
                    except Exception:
                        pass
                if payload_obj.get("escalated"):
                    tags_local.append("ESCALATED")
                return tags_local

            tags = extract_tags(payload)

            events.append({
                "id": r[0],
                "seq": r[1],
                "event_type": evt_type,
                "source_type": r[3],
                "source_id": r[4],
                "target_type": r[5],
                "target_id": r[6],
                "payload": payload,
                "created_at": r[8],
                "tags": tags,
                "latency_ms": lat,
            })

        return {"events": events, "summary": summary}
    except Exception:
        raise HTTPException(status_code=500, detail="timeline_failed")


@router.get("/{trace_id}/summary/by_time")
def summarize_by_time(trace_id: str, bucket_seconds: int = 1):
    """Aggregate decision trace by time bucket with agent counts and latency.

    - Groups events by created_at truncated to N-second buckets
    - Counts agents invoked, lists agent names, sums latency
    - Flags complexity escalation when tier >= 2 or interleaving engaged
    """
    try:
        from src.app.models.db import db_session as _db_session
        with _db_session() as db:
            try:
                rows = db.execute(
                    "SELECT id, event_type, source_id, payload, created_at FROM decision_trace_events WHERE trace_id = :trace_id ORDER BY created_at ASC",
                    {"trace_id": trace_id},
                ).fetchall()
            except Exception:
                rows = []
        # Bucketing
        buckets: dict[str, dict] = {}
        tier_escalated_at: set[str] = set()
        for r in rows or []:
            # Defensive parse
            raw_payload = r[3]
            try:
                payload = json.loads(raw_payload) if isinstance(raw_payload, str) else (raw_payload or {})
            except Exception:
                payload = {}

            # Bucket key: truncate created_at to bucket_seconds
            ts = r[4]
            try:
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00")) if isinstance(ts, str) else datetime.utcnow()
            except Exception:
                dt = datetime.utcnow()
            # Reduce to epoch seconds, then floor to bucket
            epoch = int(dt.timestamp())
            key_epoch = epoch - (epoch % max(1, int(bucket_seconds)))
            key = datetime.utcfromtimestamp(key_epoch).isoformat() + "Z"

            b = buckets.setdefault(key, {"agents": set(), "agent_count": 0, "latency_ms_total": 0, "events": 0, "tags": set(), "complexity": "T1"})
            b["events"] += 1

            # Count agent invocation events specially
            evt_type = r[1] or "event"
            if evt_type in ("agent_invocation", "model_invoke"):
                name = r[2] or payload.get("agent") or "unknown"
                b["agents"].add(name)
                b["agent_count"] = len(b["agents"])
                try:
                    v = payload.get("latency_ms")
                    if isinstance(v, (int, float)):
                        b["latency_ms_total"] += int(v)
                    elif v is not None:
                        b["latency_ms_total"] += int(float(str(v)))
                except Exception:
                    pass
                tags = payload.get("tags") if isinstance(payload, dict) else None
                if isinstance(tags, list):
                    for t in tags[:12]:
                        try:
                            b["tags"].add(str(t))
                        except Exception:
                            pass

            # Complexity escalation signals
            try:
                if evt_type == "tier_decision":
                    t = payload.get("tier")
                    if isinstance(t, (int, float)) and int(t) >= 2:
                        b["complexity"] = f"T{int(t)}"
                        tier_escalated_at.add(key)
                if evt_type == "interleaving_event":
                    b["complexity"] = "T2+"
                    tier_escalated_at.add(key)
            except Exception:
                pass

        # Finalize output: convert sets to lists
        out = []
        for k, v in sorted(buckets.items(), key=lambda x: x[0]):
            out.append({
                "bucket": k,
                "agents_invoked": sorted(list(v["agents"])),
                "agent_count": v["agent_count"],
                "latency_ms_total": v["latency_ms_total"],
                "events": v["events"],
                "tags": sorted(list(v["tags"])),
                "complexity": v["complexity"],
                "tier_escalated": (k in tier_escalated_at),
            })
        return {"buckets": out}
    except Exception:
        raise HTTPException(status_code=500, detail="summary_failed")
