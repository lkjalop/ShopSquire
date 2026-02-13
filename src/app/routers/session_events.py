from fastapi import APIRouter, Depends, HTTPException
from typing import List, Dict, Any
from sqlalchemy import text
from datetime import datetime

from src.app.models.schemas import SessionEvent
from src.app.models.db import db_session
from src.app.security.auth import require_role, ROLE_DEVELOPER, ROLE_MERCHANT, ROLE_OWNER
from src.app.deps import security_sanitize, hash_uid, hash_value
from src.app.services.geoip import resolve_asn_country

router = APIRouter(prefix="/api/v1/events", tags=["events"])


@router.post("/ingest")
def ingest_events(events: List[SessionEvent], role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER]))) -> Dict[str, Any]:
    """Ingest a batch of privacy-safe session events.

    - Hash identifiers (`uid`, `session_id`, `device_id`)
    - Sanitize `properties` for PII
    - Derive coarse `asn` and `country` from IP if available, then discard IP
    - Persist to `event_log` outbox with type `session.event`
    """
    if not events:
        raise HTTPException(status_code=400, detail="no_events")
    stored = 0
    now_iso = datetime.utcnow().isoformat()
    try:
        with db_session() as db:
            for ev in events:
                uid_h = hash_uid(ev.uid or "") if ev.uid else None
                sess_h = hash_value(ev.session_id or "") if ev.session_id else None
                dev_h = hash_value(ev.device_id or "") if ev.device_id else None
                props = security_sanitize(ev.properties or {})
                asn, country = resolve_asn_country(ev.ip)
                payload = {
                    "ts": ev.ts or now_iso,
                    "uid_hash": uid_h,
                    "session_hash": sess_h,
                    "device_hash": dev_h,
                    "action": ev.action,
                    "props": props,
                    "asn": asn,
                    "country": country,
                }
                db.execute(
                    text("INSERT INTO event_log (id, type, payload, status) VALUES (:id, :type, :payload, 'pending')"),
                    {
                        "id": hash_value(f"{sess_h}:{ev.action}:{ev.ts or now_iso}"),
                        "type": "session.event",
                        "payload": __import__("json").dumps(payload, ensure_ascii=False),
                    },
                )
                stored += 1
            db.commit()
    except Exception:
        raise HTTPException(status_code=500, detail="persist_failed")
    return {"stored": stored}
