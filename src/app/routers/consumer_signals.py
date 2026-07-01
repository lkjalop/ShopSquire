from fastapi import APIRouter, HTTPException, Depends, Request
from typing import List, Dict, Any
from datetime import datetime
import json

from src.app.models.db import db_session
from src.app.deps import hash_uid, hash_value, security_sanitize
from src.app.services.geoip import resolve_asn_country
from src.app.security.auth import require_role, ROLE_DEVELOPER, ROLE_MERCHANT, ROLE_OWNER
from src.app.services.trace_taxonomy import normalize_trace_event_type

router = APIRouter(prefix="/api/v1/consumer", tags=["consumer-signals"])


@router.post("/ingest")
def ingest_consumer_signals(events: List[Dict[str, Any]], request: Request, role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER]))):
    """Privacy-first ingestion for consumer behavior signals.

    - Accepts a batch of events. Each event may include: `uid`, `session_id`, `device_id`, `action`, `path`, `dwell_ms`, `trace_id`, `properties`, `ip`, `ts`.
    - Hashes identifiers, sanitizes properties, derives coarse ASN/country then drops raw IP.
    - If `trace_id` present the event is stored in `decision_trace_events` (real-time UI stream); otherwise falls back to `event_log` outbox.
    """
    if not events:
        raise HTTPException(status_code=400, detail="no_events")
    stored = 0
    now_iso = datetime.utcnow().isoformat()
    try:
        with db_session() as db:
            for ev in events:
                uid_h = hash_uid(ev.get("uid") or "") if ev.get("uid") else None
                sess_h = hash_value(ev.get("session_id") or "") if ev.get("session_id") else None
                dev_h = hash_value(ev.get("device_id") or "") if ev.get("device_id") else None
                props = security_sanitize(ev.get("properties") or {})
                asn, country = resolve_asn_country(ev.get("ip"))
                base_payload = {
                    "ts": ev.get("ts") or now_iso,
                    "uid_hash": uid_h,
                    "session_hash": sess_h,
                    "device_hash": dev_h,
                    "action": ev.get("action"),
                    "path": ev.get("path"),
                    "dwell_ms": ev.get("dwell_ms"),
                    "props": props,
                    "asn": asn,
                    "country": country,
                    "source_ip": None,
                }
                trace_id = ev.get("trace_id")
                if trace_id:
                    # write to decision_trace_events for real-time UI streaming
                    canonical_type, original_type = normalize_trace_event_type(ev.get("action") or "consumer.event")
                    if original_type:
                        base_payload["_original_event_type"] = original_type
                    base_payload["_event_type"] = canonical_type
                    base_payload["_schema_version"] = "1.0"
                    evt_id = ev.get("id") or hash_value(f"{trace_id}:{ev.get('action') or 'ev'}:{base_payload['ts']}")
                    db.execute(
                        "INSERT INTO decision_trace_events (id, trace_id, event_type, source_type, source_id, target_type, target_id, payload, created_at) VALUES (:id, :trace_id, :event_type, :source_type, :source_id, :target_type, :target_id, :payload, :created_at)",
                        {
                            "id": evt_id,
                            "trace_id": trace_id,
                            "event_type": canonical_type,
                            "source_type": "user",
                            "source_id": uid_h,
                            "target_type": None,
                            "target_id": None,
                            "payload": json.dumps(base_payload, ensure_ascii=False),
                            "created_at": base_payload["ts"],
                        },
                    )
                else:
                    # fallback into event_log outbox for async processing
                    out_id = hash_value(f"{sess_h}:{ev.get('action') or 'ev'}:{base_payload['ts']}")
                    db.execute(
                        "INSERT INTO event_log (id, type, payload, status) VALUES (:id, :type, :payload, 'pending')",
                        {
                            "id": out_id,
                            "type": "consumer.event",
                            "payload": json.dumps(base_payload, ensure_ascii=False),
                        },
                    )
                stored += 1
            db.commit()
    except Exception:
        raise HTTPException(status_code=500, detail="persist_failed")
    # Marketing-BI foundation: capture the visit's traffic source (utm_*/referrer/gclid) → session channel + a
    # channel-tagged market signal, so the already-built market_analysis channel/segment detectors + attribution
    # light up ("which campaign drove the sale"). ISOLATED best-effort on a fresh session — never affects the
    # privacy-first ingest above (raw IP is still dropped there; only the opaque channel is derived here).
    try:
        from src.app.services import traffic_source as _ts
        with db_session() as _tdb:
            for ev in events:
                sh = hash_value(ev.get("session_id") or "") if ev.get("session_id") else None
                if sh:
                    _ts.capture(_tdb, session_hash=sh, properties=security_sanitize(ev.get("properties") or {}),
                                action=ev.get("action"), occurred_at=ev.get("ts") or now_iso)
    except Exception:
        pass
    return {"stored": stored}
