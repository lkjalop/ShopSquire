from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

from sqlalchemy import text

from src.app.models.db import db_session
from src.app.rules.tenant_config_store import TenantConfigStore
from src.app.services.geoip import enrich_ip


_ALLOWED_ACTIONS = {"allow", "challenge", "block", "escalate"}
_ALLOWED_TYPES = {"phish", "prompt-injection", "qr", "steg", "gan", "network", "other"}
_ALLOWED_STORAGE_TARGETS = {"database", "object", "warehouse", "lakehouse", "block"}
_TENANT_STORAGE_POLICY_KEY = "security_event_storage_policy"
_tenant_cfg_store = TenantConfigStore(cache_ttl=5)
_SECURITY_EVENT_TABLE_READY = False
_ACTOR_STATE_TABLE_READY = False
_TRACE_CORRELATION_CACHE: Dict[Tuple[str, str], Dict[str, Any]] = {}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _risk_band_rank(value: Any) -> int:
    band = str(value or "low").strip().lower()
    if band == "high":
        return 3
    if band == "medium":
        return 2
    return 1


def _parse_ts(raw: Any) -> str:
    s = str(raw or "").strip()
    if not s:
        return _now_iso()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(s).astimezone(timezone.utc).isoformat()
    except Exception:
        return _now_iso()


def _norm_severity(raw: Any) -> str:
    s = str(raw or "medium").strip().lower()
    if s in {"critical", "high", "medium", "low", "info"}:
        return s
    return "medium"


def _as_float(raw: Any, default: float = 0.5) -> float:
    try:
        v = float(raw)
    except Exception:
        v = default
    return max(0.0, min(1.0, v))


def _as_bool(raw: Any) -> bool:
    if isinstance(raw, bool):
        return raw
    s = str(raw or "").strip().lower()
    return s in {"1", "true", "yes", "on"}


def _event_fingerprint(vendor: str, payload: Dict[str, Any]) -> str:
    base = json.dumps({"vendor": vendor, "payload": payload}, sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(base.encode("utf-8")).hexdigest()


def _normalize_storage_targets(parts: List[str], *, default_to_database: bool = True) -> List[str]:
    out: List[str] = []
    for p in parts:
        p = str(p or "").strip().lower()
        if not p:
            continue
        if p in {"db", "database"}:
            p = "database"
        if p in {"file", "object"}:
            p = "object"
        if p in {"warehouse"}:
            p = "warehouse"
        if p in {"lake", "lakehouse"}:
            p = "lakehouse"
        if p in {"block"}:
            p = "block"
        if p in _ALLOWED_STORAGE_TARGETS and p not in out:
            out.append(p)
    if out:
        return out
    return ["database"] if default_to_database else []


def _storage_targets() -> List[str]:
    raw = str(os.getenv("SECURITY_EVENT_STORAGE_TARGETS", "database") or "").strip().lower()
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    if not parts:
        parts = ["database"]
    return _normalize_storage_targets(parts, default_to_database=True)


def _tenant_policy_targets(tenant_id: str | None) -> List[str] | None:
    try:
        cfg = _tenant_cfg_store.get_override(_TENANT_STORAGE_POLICY_KEY, tenant_id=tenant_id)
    except Exception:
        cfg = None
    if not isinstance(cfg, dict):
        return None
    targets = cfg.get("storage_targets")
    if not isinstance(targets, list):
        return None
    normalized = _normalize_storage_targets([str(x) for x in targets if str(x).strip()], default_to_database=False)
    return normalized if normalized else None


def _append_jsonl(path: Path, item: Dict[str, Any]) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
        return True
    except Exception:
        return False


def _geo_asn_enrich(payload: Dict[str, Any]) -> Dict[str, Any]:
    src_ip = str(payload.get("src_ip") or payload.get("ip") or payload.get("client_ip") or "").strip() or None
    if not src_ip:
        return {
            "src_ip": None,
            "country": None,
            "asn": None,
            "asn_org": None,
            "is_vpn": False,
            "is_hosting": False,
            "is_tor": False,
            "geo_risk": 0.0,
        }
    geo = enrich_ip(src_ip)
    org = str(geo.get("asn_org") or "")
    org_l = org.lower()
    return {
        "src_ip": src_ip,
        "country": geo.get("country"),
        "asn": geo.get("asn"),
        "asn_org": org,
        "is_vpn": bool(geo.get("is_vpn")),
        "is_hosting": bool(geo.get("is_hosting")),
        "is_tor": ("tor" in org_l),
        "geo_risk": float(geo.get("risk") or 0.0),
    }


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    import math

    r = 6371.0
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2.0) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2.0) ** 2
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(max(1e-12, 1.0 - a)))
    return float(r * c)


def _get_actor_key(event: Dict[str, Any]) -> str | None:
    for k in ("user_id", "actor_id", "principal", "device_id"):
        v = str(event.get(k) or "").strip()
        if v:
            return f"{k}:{v}"
    return None


def _ensure_actor_state_table() -> None:
    global _ACTOR_STATE_TABLE_READY
    if _ACTOR_STATE_TABLE_READY:
        return
    with db_session() as db:
        try:
            db.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS security_event_actor_state (
                      actor_key TEXT PRIMARY KEY,
                      tenant_id TEXT NOT NULL,
                      last_event_time TEXT,
                      last_country TEXT,
                      last_ip TEXT,
                      last_asn INTEGER,
                      last_lat REAL,
                      last_lon REAL,
                      updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
            )
            db.commit()
            _ACTOR_STATE_TABLE_READY = True
        except Exception:
            try:
                db.rollback()
            except Exception:
                pass


def _compute_impossible_travel(event: Dict[str, Any], geo: Dict[str, Any]) -> Dict[str, Any]:
    tenant_id = str(event.get("tenant_id") or "default")
    actor_seed = _get_actor_key(event)
    actor_key = f"{tenant_id}:{actor_seed}" if actor_seed else None
    if not actor_key:
        return {"detected": False, "reason": "missing_actor_key"}
    _ensure_actor_state_table()

    evt_ts = _parse_ts(event.get("event_time"))
    curr_country = str(geo.get("country") or "")
    curr_ip = str(geo.get("src_ip") or "")
    curr_asn = geo.get("asn")
    lat = event.get("lat")
    lon = event.get("lon")
    try:
        curr_lat = float(lat) if lat is not None else None
        curr_lon = float(lon) if lon is not None else None
    except Exception:
        curr_lat = None
        curr_lon = None
    speed_thr = float(os.getenv("IMPOSSIBLE_TRAVEL_KMH_THRESHOLD", "900") or 900)
    short_window_s = int(float(os.getenv("IMPOSSIBLE_TRAVEL_WINDOW_SECONDS", "7200") or 7200))

    detected = False
    reason = "ok"
    speed_kmh = None
    prev_country = None

    with db_session() as db:
        row = db.execute(
            text(
                """
                SELECT last_event_time, last_country, last_ip, last_asn, last_lat, last_lon
                FROM security_event_actor_state
                WHERE actor_key = :actor_key
                """
            ),
            {"actor_key": actor_key},
        ).fetchone()
        if row:
            prev_ts = _parse_ts(row[0])
            prev_country = str(row[1] or "")
            prev_ip = str(row[2] or "")
            prev_lat = row[4]
            prev_lon = row[5]
            if prev_ts:
                delta_s = max(1.0, (datetime.fromisoformat(evt_ts.replace("Z", "+00:00")) - datetime.fromisoformat(prev_ts.replace("Z", "+00:00"))).total_seconds())
                if isinstance(prev_lat, (float, int)) and isinstance(prev_lon, (float, int)) and curr_lat is not None and curr_lon is not None:
                    km = _haversine_km(float(prev_lat), float(prev_lon), float(curr_lat), float(curr_lon))
                    speed_kmh = (km / delta_s) * 3600.0
                    if speed_kmh > speed_thr:
                        detected = True
                        reason = "speed_threshold_exceeded"
                elif prev_country and curr_country and prev_country != curr_country and delta_s <= float(short_window_s):
                    detected = True
                    reason = "country_change_short_window"
                elif prev_ip and curr_ip and prev_ip != curr_ip and delta_s <= 1800 and str(curr_asn or "") != str(row[3] or ""):
                    detected = True
                    reason = "ip_asn_change_short_window"

        db.execute(
            text(
                """
                INSERT INTO security_event_actor_state
                (actor_key, tenant_id, last_event_time, last_country, last_ip, last_asn, last_lat, last_lon, updated_at)
                VALUES (:actor_key, :tenant_id, :last_event_time, :last_country, :last_ip, :last_asn, :last_lat, :last_lon, CURRENT_TIMESTAMP)
                ON CONFLICT(actor_key) DO UPDATE SET
                  tenant_id=excluded.tenant_id,
                  last_event_time=excluded.last_event_time,
                  last_country=excluded.last_country,
                  last_ip=excluded.last_ip,
                  last_asn=excluded.last_asn,
                  last_lat=excluded.last_lat,
                  last_lon=excluded.last_lon,
                  updated_at=CURRENT_TIMESTAMP
                """
            ),
            {
                "actor_key": actor_key,
                "tenant_id": tenant_id,
                "last_event_time": evt_ts,
                "last_country": curr_country or None,
                "last_ip": curr_ip or None,
                "last_asn": int(curr_asn) if isinstance(curr_asn, int) else None,
                "last_lat": curr_lat,
                "last_lon": curr_lon,
            },
        )
        db.commit()

    return {
        "detected": bool(detected),
        "reason": reason,
        "speed_kmh": round(float(speed_kmh), 2) if isinstance(speed_kmh, (float, int)) else None,
        "threshold_kmh": float(speed_thr),
        "previous_country": prev_country,
        "current_country": curr_country or None,
    }


def normalize_vendor_payload(vendor: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    v = str(vendor or "unknown").strip().lower()
    p = payload if isinstance(payload, dict) else {}
    if v == "crowdstrike":
        trace_id = str(p.get("trace_id") or p.get("correlation_id") or p.get("detection_id") or "").strip()
        score = _as_float(p.get("confidence"), default=_as_float(p.get("score"), default=0.75))
        event_type = str(p.get("event_type") or p.get("type") or "other").strip().lower()
        out = {
            "vendor": "crowdstrike",
            "event_id": str(p.get("event_id") or p.get("detection_id") or _event_fingerprint(v, p)[:24]),
            "trace_id": trace_id or None,
            "tenant_id": str(p.get("tenant_id") or "default"),
            "event_time": _parse_ts(p.get("event_time") or p.get("timestamp")),
            "severity": _norm_severity(p.get("severity") or "high"),
            "confidence": score,
            "type": event_type if event_type in _ALLOWED_TYPES else "other",
            "src_ip": p.get("src_ip"),
            "dst_ip": p.get("dst_ip"),
            "user_id": p.get("user_id"),
            "device_id": p.get("device_id") or p.get("host_id"),
            "raw_payload": p,
        }
        geo = _geo_asn_enrich(out)
        out.update(
            {
                "geo_country": geo.get("country"),
                "asn": geo.get("asn"),
                "asn_org": geo.get("asn_org"),
                "is_vpn": geo.get("is_vpn"),
                "is_hosting": geo.get("is_hosting"),
                "is_tor": geo.get("is_tor"),
                "geo_risk": geo.get("geo_risk"),
                "impossible_travel": _compute_impossible_travel(out, geo),
            }
        )
        if isinstance(out.get("impossible_travel"), dict) and out["impossible_travel"].get("detected"):
            out["type"] = "network"
        return out
    if v in {"firewall", "generic_firewall"}:
        action = str(p.get("action") or "").lower()
        event_type = "network"
        sev = "medium" if action in {"allow", "accept"} else "high"
        conf = 0.55 if action in {"allow", "accept"} else 0.8
        out = {
            "vendor": "firewall",
            "event_id": str(p.get("event_id") or p.get("log_id") or _event_fingerprint(v, p)[:24]),
            "trace_id": str(p.get("trace_id") or p.get("correlation_id") or "").strip() or None,
            "tenant_id": str(p.get("tenant_id") or "default"),
            "event_time": _parse_ts(p.get("event_time") or p.get("timestamp")),
            "severity": _norm_severity(p.get("severity") or sev),
            "confidence": _as_float(p.get("confidence"), default=conf),
            "type": event_type,
            "src_ip": p.get("src_ip"),
            "dst_ip": p.get("dst_ip"),
            "user_id": p.get("user_id"),
            "device_id": p.get("device_id"),
            "raw_payload": p,
        }
        geo = _geo_asn_enrich(out)
        out.update(
            {
                "geo_country": geo.get("country"),
                "asn": geo.get("asn"),
                "asn_org": geo.get("asn_org"),
                "is_vpn": geo.get("is_vpn"),
                "is_hosting": geo.get("is_hosting"),
                "is_tor": geo.get("is_tor"),
                "geo_risk": geo.get("geo_risk"),
                "impossible_travel": _compute_impossible_travel(out, geo),
            }
        )
        return out
    # siem/default passthrough
    event_type = str(p.get("type") or p.get("event_type") or "other").strip().lower()
    out = {
        "vendor": v or "siem",
        "event_id": str(p.get("event_id") or _event_fingerprint(v, p)[:24]),
        "trace_id": str(p.get("trace_id") or p.get("correlation_id") or "").strip() or None,
        "tenant_id": str(p.get("tenant_id") or "default"),
        "event_time": _parse_ts(p.get("event_time") or p.get("timestamp")),
        "severity": _norm_severity(p.get("severity") or "medium"),
        "confidence": _as_float(p.get("confidence"), default=0.6),
        "type": event_type if event_type in _ALLOWED_TYPES else "other",
        "src_ip": p.get("src_ip"),
        "dst_ip": p.get("dst_ip"),
        "user_id": p.get("user_id"),
        "device_id": p.get("device_id"),
        "raw_payload": p,
    }
    geo = _geo_asn_enrich(out)
    out.update(
        {
            "geo_country": geo.get("country"),
            "asn": geo.get("asn"),
            "asn_org": geo.get("asn_org"),
            "is_vpn": geo.get("is_vpn"),
            "is_hosting": geo.get("is_hosting"),
            "is_tor": geo.get("is_tor"),
            "geo_risk": geo.get("geo_risk"),
            "impossible_travel": _compute_impossible_travel(out, geo),
        }
    )
    return out


def decide_policy_action(canonical_event: Dict[str, Any]) -> Dict[str, Any]:
    sev = str(canonical_event.get("severity") or "medium").lower()
    conf = _as_float(canonical_event.get("confidence"), 0.5)
    t = str(canonical_event.get("type") or "other").lower()
    impossible_travel = bool((canonical_event.get("impossible_travel") or {}).get("detected"))
    geo_risk = _as_float(canonical_event.get("geo_risk"), 0.0)
    is_tor = _as_bool(canonical_event.get("is_tor"))
    is_vpn = _as_bool(canonical_event.get("is_vpn"))

    action = "allow"
    reason = "low_risk"
    risk_score = conf
    if sev in {"critical"} or conf >= 0.9:
        action = "block"
        reason = "critical_or_very_high_confidence"
        risk_score = max(conf, 0.95)
    elif impossible_travel and (geo_risk >= 0.7 or is_tor):
        action = "block"
        reason = "impossible_travel_high_geo_risk"
        risk_score = max(conf, 0.95)
    elif impossible_travel:
        action = "escalate"
        reason = "impossible_travel_detected"
        risk_score = max(conf, 0.82)
    elif geo_risk >= 0.85 or is_tor:
        action = "escalate"
        reason = "geoip_high_risk_or_tor"
        risk_score = max(conf, 0.82)
    elif is_vpn and conf >= 0.6:
        action = "challenge"
        reason = "vpn_source_step_up"
        risk_score = max(conf, 0.68)
    elif sev == "high":
        action = "escalate"
        reason = "high_severity_event"
        risk_score = max(conf, 0.8)
    elif t in {"prompt-injection", "phish", "network"} and conf >= 0.65:
        action = "challenge"
        reason = "suspicious_signal_requires_step_up"
        risk_score = max(conf, 0.65)
    elif sev in {"medium"} and conf >= 0.45:
        action = "challenge"
        reason = "medium_signal_review"
        risk_score = max(conf, 0.5)

    if action not in _ALLOWED_ACTIONS:
        action = "allow"
    return {
        "action": action,
        "reason": reason,
        "risk_score": round(float(risk_score), 4),
        "risk_band": ("high" if risk_score >= 0.75 else "medium" if risk_score >= 0.45 else "low"),
    }


def ensure_security_event_ingest_table() -> None:
    global _SECURITY_EVENT_TABLE_READY
    if _SECURITY_EVENT_TABLE_READY:
        return
    with db_session() as db:
        try:
            db.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS security_event_ingest (
                      id TEXT PRIMARY KEY,
                      event_uid TEXT UNIQUE,
                      tenant_id TEXT NOT NULL,
                      trace_id TEXT,
                      vendor TEXT NOT NULL,
                      event_type TEXT,
                      severity TEXT,
                      confidence REAL,
                      policy_action TEXT,
                      policy_reason TEXT,
                      risk_score REAL,
                      risk_band TEXT,
                      src_ip TEXT,
                      dst_ip TEXT,
                      user_id TEXT,
                      device_id TEXT,
                      geo_country TEXT,
                      asn INTEGER,
                      asn_org TEXT,
                      is_vpn INTEGER,
                      is_hosting INTEGER,
                      is_tor INTEGER,
                      geo_risk REAL,
                      impossible_travel INTEGER,
                      event_time TEXT,
                      raw_payload_json TEXT,
                      canonical_json TEXT,
                      policy_json TEXT,
                      created_at TEXT DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
            )
            for alter in [
                "ALTER TABLE security_event_ingest ADD COLUMN geo_country TEXT",
                "ALTER TABLE security_event_ingest ADD COLUMN asn INTEGER",
                "ALTER TABLE security_event_ingest ADD COLUMN asn_org TEXT",
                "ALTER TABLE security_event_ingest ADD COLUMN is_vpn INTEGER",
                "ALTER TABLE security_event_ingest ADD COLUMN is_hosting INTEGER",
                "ALTER TABLE security_event_ingest ADD COLUMN is_tor INTEGER",
                "ALTER TABLE security_event_ingest ADD COLUMN geo_risk REAL",
                "ALTER TABLE security_event_ingest ADD COLUMN impossible_travel INTEGER",
            ]:
                try:
                    db.execute(text(alter))
                except Exception:
                    pass
            db.commit()
            _SECURITY_EVENT_TABLE_READY = True
        except Exception:
            try:
                db.rollback()
            except Exception:
                pass


def ingest_security_event(vendor: str, payload: Dict[str, Any], storage_targets: List[str] | None = None) -> Dict[str, Any]:
    ensure_security_event_ingest_table()
    canonical = normalize_vendor_payload(vendor, payload if isinstance(payload, dict) else {})
    policy = decide_policy_action(canonical)
    uid = _event_fingerprint(str(vendor or ""), payload if isinstance(payload, dict) else {})
    rid = f"sei-{uid[:24]}"
    tenant_id = str(canonical.get("tenant_id") or "default")
    req_targets = _normalize_storage_targets([str(t) for t in (storage_targets or []) if str(t).strip()], default_to_database=False) if storage_targets else []
    policy_targets = _tenant_policy_targets(tenant_id) or []
    targets = req_targets or policy_targets or _storage_targets()
    if not targets:
        targets = ["database"]
    storage_results: Dict[str, bool] = {k: False for k in targets}
    record = {
        "id": rid,
        "event_uid": uid,
        "canonical": canonical,
        "policy": policy,
        "tenant_id": str(canonical.get("tenant_id") or "default"),
        "trace_id": canonical.get("trace_id"),
        "created_at": _now_iso(),
    }

    db_stored = False
    db_deduped = False
    if "database" in targets:
        with db_session() as db:
            try:
                existing = db.execute(
                    text(
                        """
                        SELECT id, policy_action, policy_reason, risk_score, risk_band
                        FROM security_event_ingest WHERE event_uid = :uid
                        """
                    ),
                    {"uid": uid},
                ).fetchone()
            except Exception:
                existing = None
            if existing:
                rid = str(existing[0])
                policy = {
                    "action": str(existing[1] or "allow"),
                    "reason": str(existing[2] or ""),
                    "risk_score": float(existing[3] or 0.0),
                    "risk_band": str(existing[4] or "low"),
                }
                db_stored = True
                db_deduped = True
            else:
                try:
                    db.execute(
                        text(
                            """
                            INSERT INTO security_event_ingest (
                              id, event_uid, tenant_id, trace_id, vendor, event_type, severity, confidence,
                              policy_action, policy_reason, risk_score, risk_band, src_ip, dst_ip, user_id, device_id,
                              geo_country, asn, asn_org, is_vpn, is_hosting, is_tor, geo_risk, impossible_travel,
                              event_time, raw_payload_json, canonical_json, policy_json
                            ) VALUES (
                              :id, :event_uid, :tenant_id, :trace_id, :vendor, :event_type, :severity, :confidence,
                              :policy_action, :policy_reason, :risk_score, :risk_band, :src_ip, :dst_ip, :user_id, :device_id,
                              :geo_country, :asn, :asn_org, :is_vpn, :is_hosting, :is_tor, :geo_risk, :impossible_travel,
                              :event_time, :raw_payload_json, :canonical_json, :policy_json
                            )
                            """
                        ),
                        {
                            "id": rid,
                            "event_uid": uid,
                            "tenant_id": str(canonical.get("tenant_id") or "default"),
                            "trace_id": canonical.get("trace_id"),
                            "vendor": str(canonical.get("vendor") or "unknown"),
                            "event_type": str(canonical.get("type") or "other"),
                            "severity": str(canonical.get("severity") or "medium"),
                            "confidence": float(canonical.get("confidence") or 0.0),
                            "policy_action": str(policy.get("action") or "allow"),
                            "policy_reason": str(policy.get("reason") or ""),
                            "risk_score": float(policy.get("risk_score") or 0.0),
                            "risk_band": str(policy.get("risk_band") or "low"),
                            "src_ip": canonical.get("src_ip"),
                            "dst_ip": canonical.get("dst_ip"),
                            "user_id": canonical.get("user_id"),
                            "device_id": canonical.get("device_id"),
                            "geo_country": canonical.get("geo_country"),
                            "asn": canonical.get("asn"),
                            "asn_org": canonical.get("asn_org"),
                            "is_vpn": 1 if _as_bool(canonical.get("is_vpn")) else 0,
                            "is_hosting": 1 if _as_bool(canonical.get("is_hosting")) else 0,
                            "is_tor": 1 if _as_bool(canonical.get("is_tor")) else 0,
                            "geo_risk": float(canonical.get("geo_risk") or 0.0),
                            "impossible_travel": 1 if _as_bool((canonical.get("impossible_travel") or {}).get("detected")) else 0,
                            "event_time": str(canonical.get("event_time") or _now_iso()),
                            "raw_payload_json": json.dumps(payload if isinstance(payload, dict) else {}, ensure_ascii=False),
                            "canonical_json": json.dumps(canonical, ensure_ascii=False),
                            "policy_json": json.dumps(policy, ensure_ascii=False),
                        },
                    )
                    db.commit()
                    db_stored = True
                    db_deduped = False
                except Exception:
                    try:
                        row = db.execute(
                            text(
                                """
                                SELECT id, policy_action, policy_reason, risk_score, risk_band
                                FROM security_event_ingest WHERE event_uid = :uid
                                """
                            ),
                            {"uid": uid},
                        ).fetchone()
                    except Exception:
                        row = None
                    db_stored = bool(row)
                    db_deduped = bool(row)
                    if row:
                        rid = str(row[0])
                        policy = {
                            "action": str(row[1] or "allow"),
                            "reason": str(row[2] or ""),
                            "risk_score": float(row[3] or 0.0),
                            "risk_band": str(row[4] or "low"),
                        }
                    try:
                        db.rollback()
                    except Exception:
                        pass
        storage_results["database"] = bool(db_stored)

    created_dt = datetime.now(timezone.utc)
    if "object" in targets:
        root = Path(str(os.getenv("SECURITY_EVENT_OBJECT_PATH", "data/security-events/object") or "data/security-events/object"))
        object_path = root / f"{created_dt.strftime('%Y%m%d')}.jsonl"
        storage_results["object"] = _append_jsonl(object_path, record)
    if "warehouse" in targets:
        root = Path(str(os.getenv("SECURITY_EVENT_WAREHOUSE_PATH", "data/security-events/warehouse") or "data/security-events/warehouse"))
        wh_path = root / f"dt={created_dt.strftime('%Y-%m-%d')}" / "events.jsonl"
        storage_results["warehouse"] = _append_jsonl(wh_path, record)
    if "lakehouse" in targets:
        root = Path(str(os.getenv("SECURITY_EVENT_LAKEHOUSE_PATH", "data/security-events/lakehouse") or "data/security-events/lakehouse"))
        lh_path = root / f"year={created_dt.year}" / f"month={created_dt.month:02d}" / f"day={created_dt.day:02d}" / "events.jsonl"
        storage_results["lakehouse"] = _append_jsonl(lh_path, record)
    if "block" in targets:
        # "block" sink is represented as content-addressable append logs (immutable-ish local simulation).
        root = Path(str(os.getenv("SECURITY_EVENT_BLOCK_PATH", "data/security-events/block") or "data/security-events/block"))
        blk_path = root / uid[:2] / f"{uid}.json"
        storage_results["block"] = _append_jsonl(blk_path, record)

    trace_id = str(canonical.get("trace_id") or "").strip()
    tenant_key = str(canonical.get("tenant_id") or "default")
    cache_key = (tenant_key, trace_id) if trace_id else None
    if cache_key and "database" in targets:
        cache_entry = _TRACE_CORRELATION_CACHE.get(cache_key)
        if db_stored and not db_deduped:
            highest_rank = max(_risk_band_rank(policy.get("risk_band")), int(cache_entry.get("highest_rank") or 1)) if cache_entry else _risk_band_rank(policy.get("risk_band"))
            sources = set(cache_entry.get("sources") or []) if cache_entry else set()
            sources.add(str(canonical.get("vendor") or "unknown"))
            cache_entry = {
                "event_count": (int(cache_entry.get("event_count") or 0) + 1) if cache_entry else 1,
                "sources": sorted(sources),
                "highest_rank": highest_rank,
            }
            _TRACE_CORRELATION_CACHE[cache_key] = cache_entry
        if cache_entry:
            corr = {
                "trace_id": trace_id,
                "tenant_id": tenant_key,
                "event_count": int(cache_entry.get("event_count") or 0),
                "sources": list(cache_entry.get("sources") or []),
                "highest_risk_band": "high" if int(cache_entry.get("highest_rank") or 1) >= 3 else "medium" if int(cache_entry.get("highest_rank") or 1) == 2 else "low",
                "multi_source": len(list(cache_entry.get("sources") or [])) >= 2,
            }
        else:
            corr = correlate_by_trace(trace_id=trace_id, tenant_id=tenant_key)
            _TRACE_CORRELATION_CACHE[cache_key] = {
                "event_count": int(corr.get("event_count") or 0),
                "sources": list(corr.get("sources") or []),
                "highest_rank": _risk_band_rank(corr.get("highest_risk_band")),
            }
    else:
        corr = correlate_by_trace(trace_id=canonical.get("trace_id"), tenant_id=canonical.get("tenant_id"))
    return {
        "ok": True,
        "id": rid,
        "deduped": bool(db_deduped),
        "stored": bool(any(storage_results.values())),
        "storage_targets": targets,
        "storage_results": storage_results,
        "canonical": canonical,
        "policy": policy,
        "correlation": corr,
    }


def correlate_by_trace(trace_id: Any, tenant_id: Any) -> Dict[str, Any]:
    tid = str(trace_id or "").strip()
    ten = str(tenant_id or "").strip() or "default"
    if not tid:
        return {"trace_id": None, "tenant_id": ten, "event_count": 0, "sources": [], "highest_risk_band": "low"}
    event_count = 0
    source_count = 0
    highest_rank = 1
    sources: List[str] = []
    with db_session() as db:
        try:
            row = db.execute(
                text(
                    """
                    SELECT
                      COUNT(1) AS event_count,
                      COUNT(DISTINCT vendor) AS source_count,
                      MAX(CASE risk_band WHEN 'high' THEN 3 WHEN 'medium' THEN 2 ELSE 1 END) AS highest_rank,
                      GROUP_CONCAT(DISTINCT vendor) AS vendors
                    FROM security_event_ingest
                    WHERE trace_id = :t AND tenant_id = :ten
                    """
                ),
                {"t": tid, "ten": ten},
            ).fetchone()
        except Exception:
            row = None
    if row:
        try:
            event_count = int(row[0] or 0)
        except Exception:
            event_count = 0
        try:
            source_count = int(row[1] or 0)
        except Exception:
            source_count = 0
        try:
            highest_rank = int(row[2] or 1)
        except Exception:
            highest_rank = 1
        vendors_blob = str(row[3] or "").strip()
        sources = sorted([part.strip() for part in vendors_blob.split(",") if part.strip()]) if vendors_blob else []
    highest_band = "high" if highest_rank >= 3 else "medium" if highest_rank == 2 else "low"
    return {
        "trace_id": tid,
        "tenant_id": ten,
        "event_count": event_count,
        "sources": sources,
        "highest_risk_band": highest_band,
        "multi_source": source_count >= 2,
    }


def replay_event_policy(event_id: str) -> Dict[str, Any]:
    ensure_security_event_ingest_table()
    with db_session() as db:
        row = db.execute(
            text("SELECT canonical_json, policy_json FROM security_event_ingest WHERE id = :id"),
            {"id": str(event_id)},
        ).fetchone()
    if not row:
        return {"ok": False, "reason": "event_not_found"}
    try:
        canonical = json.loads(str(row[0] or "{}"))
    except Exception:
        canonical = {}
    try:
        stored = json.loads(str(row[1] or "{}"))
    except Exception:
        stored = {}
    recomputed = decide_policy_action(canonical)
    return {
        "ok": True,
        "event_id": str(event_id),
        "stored_policy": stored,
        "recomputed_policy": recomputed,
        "deterministic_match": stored == recomputed,
    }


def get_tenant_storage_policy(tenant_id: str | None) -> Dict[str, Any]:
    tid = str(tenant_id or "global")
    cfg = _tenant_cfg_store.get_override(_TENANT_STORAGE_POLICY_KEY, tenant_id=tenant_id) or {}
    targets = _normalize_storage_targets([str(x) for x in (cfg.get("storage_targets") or []) if str(x).strip()], default_to_database=False) if isinstance(cfg, dict) else []
    return {
        "tenant_id": tid,
        "config_key": _TENANT_STORAGE_POLICY_KEY,
        "storage_targets": targets,
        "effective_storage_targets": targets or _storage_targets(),
        "source": ("tenant_policy" if targets else "env_default"),
    }


def put_tenant_storage_policy(tenant_id: str | None, storage_targets: List[str]) -> Dict[str, Any]:
    targets = _normalize_storage_targets([str(x) for x in (storage_targets or []) if str(x).strip()], default_to_database=False)
    if not targets:
        raise ValueError("storage_targets_required")
    ok = _tenant_cfg_store.set_override(_TENANT_STORAGE_POLICY_KEY, {"storage_targets": targets}, tenant_id=tenant_id)
    if not ok:
        raise RuntimeError("storage_policy_write_failed")
    return get_tenant_storage_policy(tenant_id)


def delete_tenant_storage_policy(tenant_id: str | None) -> Dict[str, Any]:
    ok = _tenant_cfg_store.delete_override(_TENANT_STORAGE_POLICY_KEY, tenant_id=tenant_id)
    if not ok:
        raise RuntimeError("storage_policy_delete_failed")
    return get_tenant_storage_policy(tenant_id)
