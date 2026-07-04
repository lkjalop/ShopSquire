import os
from typing import List, Dict, Any, Optional
from datetime import datetime
import json

from fastapi import APIRouter, HTTPException, Request, Header
from pydantic import BaseModel

from src.app.models.db import db_session
from src.app.deps import hash_uid, hash_value, security_sanitize
from src.app.services.geoip import resolve_asn_country
from src.app.security.auth import get_role_from_key
from src.app.services.trace_taxonomy import normalize_trace_event_type

router = APIRouter(prefix="/api/v1/consumer", tags=["consumer-signals"])


def _anon_ingest_allowed() -> bool:
    return str(os.getenv("CONSUMER_INGEST_ALLOW_ANON", "0")).strip().lower() in ("1", "true", "yes", "on")


@router.post("/ingest")
def ingest_consumer_signals(events: List[Dict[str, Any]], request: Request,
                            x_api_key: Optional[str] = Header(default=None, alias="x-api-key")):
    """Privacy-first ingestion for consumer behavior signals.

    - Accepts a batch of events. Each event may include: `uid`, `session_id`, `device_id`, `action`, `path`, `dwell_ms`, `trace_id`, `properties`, `ip`, `ts`.
    - Hashes identifiers, sanitizes properties, derives coarse ASN/country then drops raw IP.
    - If `trace_id` present the event is stored in `decision_trace_events` (real-time UI stream); otherwise falls back to `event_log` outbox.

    AUTH: an operator key is accepted (the demo shopper carries one). A REAL buyer's browser has no operator
    key, so Track-2b would 401 for exactly its target population; when CONSUMER_INGEST_ALLOW_ANON is enabled
    an ANONYMOUS shopper is accepted and RATE-LIMITED per source (the payload is hashed/sanitized + IP-dropped
    regardless). Default OFF keeps the endpoint operator-gated — no security change unless a pilot opts in.
    """
    role = get_role_from_key(x_api_key)
    if not role and not _anon_ingest_allowed():
        raise HTTPException(status_code=401, detail="unauthorized")
    if not events:
        raise HTTPException(status_code=400, detail="no_events")
    if not role:
        # anonymous buyer telemetry → bound abuse per source (fail-open if the limiter backend is down)
        try:
            from src.app.security.rate_limit import consume_fixed_window_limit
            src_key = request.client.host if (request and request.client) else "anon"
            if not consume_fixed_window_limit(key=f"consumer_ingest:{src_key}", limit=120, window_sec=60):
                raise HTTPException(status_code=429, detail="rate_limited")
        except HTTPException:
            raise
        except Exception:
            pass
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
        from src.app.services.geoip import enrich_ip as _enrich_ip
        with db_session() as _tdb:
            for ev in events:
                sh = hash_value(ev.get("session_id") or "") if ev.get("session_id") else None
                if not sh:
                    continue
                # repurpose the fraud-grade network flags for VERIFIED-HUMAN traffic quality: a datacenter/
                # VPN/Tor visit is bot-suspect. Derived from the IP here then discarded — only the boolean is kept.
                _coarse_net = None
                try:
                    _net = _enrich_ip(ev.get("ip")) or {}
                    _bot = bool(_net.get("is_hosting") or _net.get("is_vpn") or _net.get("is_tor"))
                    # keep a COARSE, non-PII fingerprint {asn, country, risk_tier} for BI + security forensics;
                    # the raw IP is still dropped — only these region/network-grade fields survive.
                    _coarse_net = _ts._coarsen_network(_net)
                except Exception:
                    _bot = False
                _ts.capture(_tdb, session_hash=sh, properties=security_sanitize(ev.get("properties") or {}),
                            action=ev.get("action"), bot_suspect=_bot, occurred_at=ev.get("ts") or now_iso,
                            network=_coarse_net)
    except Exception:
        pass
    return {"stored": stored}


# ── Capability-gap ledger — "what users asked for that we couldn't/wouldn't do" ─────────────────────────
# Every honest refusal is product signal: the storefront POSTs one row per unmet request (unsupported
# action / unmet search / refused+injection attempt); QA reads the rollup at the weekly roadmap review.

class CapabilityGapIn(BaseModel):
    utterance: str
    category: str = "unsupported_action"
    refusal_reason: str = ""
    surface: str = "chat"
    uid: Optional[str] = None
    trace_id: Optional[str] = None


@router.post("/capability-gap")
def record_capability_gap(payload: CapabilityGapIn, request: Request,
                          x_api_key: Optional[str] = Header(default=None)) -> Dict[str, Any]:
    """Record ONE capability gap (rate-limited like ingest; anonymous allowed only when the ingest flag
    permits it — the storefront ships a key). Body text is sanitized; uid stored as a hash only."""
    role = get_role_from_key(x_api_key)
    if not role and not _anon_ingest_allowed():
        raise HTTPException(status_code=401, detail="API key required")
    try:
        from src.app.security.rate_limit import consume_fixed_window_limit
        ok, _ = consume_fixed_window_limit(f"capgap:{request.client.host if request.client else 'na'}",
                                           limit=60, window_seconds=60)
        if not ok:
            raise HTTPException(status_code=429, detail="rate_limited")
    except HTTPException:
        raise
    except Exception:
        pass
    from src.app.services.capability_gap import record_gap
    with db_session() as db:
        stored = record_gap(
            db, category=str(payload.category), utterance=security_sanitize(payload.utterance),
            refusal_reason=str(payload.refusal_reason or ""), surface=str(payload.surface or "chat"),
            uid_hash=(hash_uid(payload.uid) if payload.uid else None), trace_id=payload.trace_id)
    return {"stored": bool(stored)}


@router.get("/capability-gaps")
def list_capability_gaps(x_api_key: Optional[str] = Header(default=None), limit: int = 50) -> Dict[str, Any]:
    """QA/roadmap rollup (operator-only): per-category counts + recent examples."""
    role = get_role_from_key(x_api_key)
    if role not in ("owner", "merchant", "developer"):
        raise HTTPException(status_code=401, detail="operator key required")
    from src.app.services.capability_gap import gap_rollup
    with db_session() as db:
        return gap_rollup(db, limit=max(1, min(int(limit or 50), 200)))
