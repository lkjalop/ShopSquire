from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Dict, List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text, bindparam
from pydantic import BaseModel

from src.app.deps import get_redis, hash_uid
from src.app.models.db import db_session
from src.app.policy.route_enforcement import enforce_action_authority
from src.app.security.auth import require_role, ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER
from src.app.security.dlp_export import dlp_sanitize_export_value
from src.app.services.memory import Memory
from src.app.services.decision_log import log_trace_event


router = APIRouter(prefix="/api/v1/privacy", tags=["privacy"])
_PRIVACY_FALLBACK: Dict[str, str] = {}


class PrivacyConsentPayload(BaseModel):
    personalization_opt_in: bool = False
    retention_opt_in: bool = False
    ai_disclosure_ack: bool = False
    locale: str | None = None
    region: str | None = None


class PrivacyRequestPayload(BaseModel):
    request_type: str
    reason: str | None = None
    locale: str | None = None


def _safe_json(value):
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except Exception:
        return value


def _redact_value(val):
    if val is None:
        return None
    if isinstance(val, (dict, list)):
        return _redact_json(val)
    # simple scalar redaction
    return "<REDACTED>"


def _redact_json(obj):
    sensitive_keys = {"email", "phone", "name", "address", "credit_card", "cc_number", "card_number", "ssn", "social_security", "full_name"}
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            lk = k.lower()
            if any(token in lk for token in ("token", "secret", "password")) or lk in sensitive_keys or any(s in lk for s in ("email","phone","card","ssn","social")):
                out[k] = _redact_value(v)
            else:
                out[k] = _redact_json(v) if isinstance(v, (dict, list)) else v
        return out
    elif isinstance(obj, list):
        return [_redact_json(v) if isinstance(v, (dict, list)) else v for v in obj]
    else:
        return obj


def _uid_patterns(uid: str, uid_hash: str) -> tuple[str, Dict[str, str]]:
    patterns = [
        f'%\"uid\": \"{uid}\"%',
        f'%\"uid\":\"{uid}\"%',
        f'%\"uid_hash\": \"{uid_hash}\"%',
        f'%\"uid_hash\":\"{uid_hash}\"%',
    ]
    where = " OR ".join([f"input_data LIKE :p{i}" for i in range(len(patterns))])
    params = {f"p{i}": pat for i, pat in enumerate(patterns)}
    return where, params


_UID_WHERE_SQL = "(input_data LIKE :p0 OR input_data LIKE :p1 OR input_data LIKE :p2 OR input_data LIKE :p3)"


def _in_clause(prefix: str, values: List[str]) -> tuple[str, Dict[str, str]]:
    keys = []
    params: Dict[str, str] = {}
    for i, v in enumerate(values):
        key = f"{prefix}{i}"
        keys.append(f":{key}")
        params[key] = v
    return ", ".join(keys), params


def _consent_key(uid: str) -> str:
    return f"privacy:{uid}:consent"


def _request_key(uid: str) -> str:
    return f"privacy:{uid}:requests"


def _kv_get(redis, key: str):
    try:
        val = redis.get(key)
        if val is None:
            return _PRIVACY_FALLBACK.get(key)
        return val
    except Exception:
        return _PRIVACY_FALLBACK.get(key)


def _kv_set(redis, key: str, value: str) -> None:
    try:
        redis.set(key, value)
    except Exception:
        _PRIVACY_FALLBACK[key] = value


@router.get("/consent/{uid}")
def get_consent(
    uid: str,
    redis=Depends(get_redis),
    role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict:
    try:
        raw = _kv_get(redis, _consent_key(uid))
        payload = _safe_json(raw) if raw else {}
        if not isinstance(payload, dict):
            payload = {}
        return {
            "uid": uid,
            "uid_hash": hash_uid(uid),
            "consent": payload,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/consent/{uid}")
def set_consent(
    uid: str,
    body: PrivacyConsentPayload,
    redis=Depends(get_redis),
    role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict:
    payload = {
        "personalization_opt_in": bool(body.personalization_opt_in),
        "retention_opt_in": bool(body.retention_opt_in),
        "ai_disclosure_ack": bool(body.ai_disclosure_ack),
        "locale": body.locale or "en",
        "region": body.region,
        "updated_at": datetime.utcnow().isoformat(),
        "consent_version": "v1",
    }
    try:
        _kv_set(redis, _consent_key(uid), json.dumps(payload, ensure_ascii=False))
        # Best-effort audit in decision trace stream for admin drilldown visibility.
        try:
            log_trace_event(
                trace_id=uid,
                event_type="privacy_consent_updated",
                source_type="agent",
                source_id="Privacy_Agent",
                target_type="user",
                target_id=uid,
                payload={
                    "uid_hash": hash_uid(uid),
                    "consent": payload,
                    "compliance_tags": [
                        "privacy:consent_recorded",
                        "gdpr:consent_state",
                    ],
                },
            )
        except Exception:
            pass
        return {"ok": True, "uid": uid, "uid_hash": hash_uid(uid), "consent": payload}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/request/{uid}")
def create_privacy_request(
    uid: str,
    body: PrivacyRequestPayload,
    redis=Depends(get_redis),
    role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict:
    request_type = str(body.request_type or "").strip().lower()
    if request_type not in {"export", "delete", "optout_automation"}:
        raise HTTPException(status_code=400, detail="request_type must be one of: export, delete, optout_automation")
    entry = {
        "id": f"prv_{uuid.uuid4().hex[:12]}",
        "uid": uid,
        "uid_hash": hash_uid(uid),
        "request_type": request_type,
        "reason": body.reason,
        "locale": body.locale or "en",
        "status": "received",
        "created_at": datetime.utcnow().isoformat(),
    }
    try:
        raw = _kv_get(redis, _request_key(uid))
        items = _safe_json(raw) if raw else []
        if not isinstance(items, list):
            items = []
        items.append(entry)
        _kv_set(redis, _request_key(uid), json.dumps(items[-100:], ensure_ascii=False))
        try:
            log_trace_event(
                trace_id=uid,
                event_type="privacy_request_created",
                source_type="agent",
                source_id="Privacy_Agent",
                target_type="system",
                target_id="Privacy_Queue",
                payload={
                    "request": entry,
                    "compliance_tags": [
                        "gdpr:rights_request",
                        f"gdpr:{request_type}",
                    ],
                },
            )
        except Exception:
            pass
        return {"ok": True, "request": entry}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.delete("/data/{uid}")
def delete_user_data(uid: str, redis=Depends(get_redis), role: str = Depends(require_role([ROLE_OWNER]))) -> Dict:
    """GDPR Article 17: Right to Erasure."""
    uid_hash = hash_uid(uid)
    deleted = {
        "decision_logs": 0,
        "decision_audits": 0,
        "chat_messages": 0,
        "order_sessions": 0,
        "orders": 0,
        "draft_orders": 0,
        "customers": 0,
        "session_memory": False,
    }
    try:
        with db_session() as db:
            _where, params = _uid_patterns(uid, uid_hash)
            ids = db.execute(text(f"SELECT id FROM decision_logs WHERE {_UID_WHERE_SQL}"), params).fetchall()
            decision_ids = [r[0] for r in ids if r and r[0]]
            if decision_ids:
                in_params = {"decision_ids": decision_ids}
                res = db.execute(
                    text("DELETE FROM decision_audits WHERE decision_id IN :decision_ids").bindparams(
                        bindparam("decision_ids", expanding=True)
                    ),
                    in_params,
                )
                deleted["decision_audits"] = getattr(res, "rowcount", 0) or 0
                res = db.execute(
                    text("DELETE FROM decision_logs WHERE id IN :decision_ids").bindparams(
                        bindparam("decision_ids", expanding=True)
                    ),
                    in_params,
                )
                deleted["decision_logs"] = getattr(res, "rowcount", 0) or 0

            res = db.execute(text("DELETE FROM order_sessions WHERE uid = :uid"), {"uid": uid})
            deleted["order_sessions"] = getattr(res, "rowcount", 0) or 0

            try:
                res = db.execute(text("DELETE FROM chat_messages WHERE uid = :uid"), {"uid": uid})
                deleted["chat_messages"] = getattr(res, "rowcount", 0) or 0
            except Exception:
                deleted["chat_messages"] = 0

            res = db.execute(
                "UPDATE orders SET customer_id = 'DELETED' WHERE customer_id = :uid",
                {"uid": uid},
            )
            deleted["orders"] = getattr(res, "rowcount", 0) or 0

            res = db.execute(text("DELETE FROM draft_orders WHERE customer_id = :uid"), {"uid": uid})
            deleted["draft_orders"] = getattr(res, "rowcount", 0) or 0

            res = db.execute(text("DELETE FROM customers WHERE id = :uid"), {"uid": uid})
            deleted["customers"] = getattr(res, "rowcount", 0) or 0

            db.commit()

        try:
            # DSR erasure across ALL user-linked Redis keys (8 memory + typed
            # artifacts) via the single inventory — not just the 3 keys cleared
            # historically (GDPR/APP right-to-erasure).
            from src.app.services.user_data_inventory import erase_redis
            deleted["session_memory"] = erase_redis(redis, uid)
        except Exception:
            deleted["session_memory"] = False

        return {"status": "deleted", "uid": uid, "uid_hash": uid_hash, "deleted_records": deleted}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/export/{uid}")
def export_user_data(uid: str, redis=Depends(get_redis), redact: bool = False, role: str = Depends(require_role([ROLE_OWNER, ROLE_MERCHANT]))) -> Dict:
    """GDPR Article 20: Right to Data Portability."""
    enforce_action_authority(
        "pii_export",
        context={"uid": uid, "requested_by_role": role, "redact": bool(redact)},
    )
    uid_hash = hash_uid(uid)
    export = {
        "uid": uid,
        "uid_hash": uid_hash,
        "exported_at": datetime.utcnow().isoformat(),
        "chat_messages": [],
        "customers": [],
        "orders": [],
        "order_sessions": [],
        "draft_orders": [],
        "decision_logs": [],
        "decision_audits": [],
        "session_memory": None,
    }
    try:
        with db_session() as db:
            rows = db.execute(text("SELECT * FROM customers WHERE id = :uid"), {"uid": uid}).mappings().all()
            export["customers"] = [dict(r) for r in rows]

            rows = db.execute(text("SELECT * FROM order_sessions WHERE uid = :uid"), {"uid": uid}).mappings().all()
            export["order_sessions"] = [dict(r) for r in rows]
            order_ids = [r.get("order_id") for r in export["order_sessions"] if r.get("order_id")]

            try:
                rows = db.execute(
                    text(
                        "SELECT id, uid, session_id, role, content, trace_id, created_at "
                        "FROM chat_messages WHERE uid = :uid ORDER BY created_at DESC LIMIT 1000"
                    ),
                    {"uid": uid},
                ).mappings().all()
                export["chat_messages"] = [dict(r) for r in rows]
            except Exception:
                export["chat_messages"] = []

            if order_ids:
                rows = db.execute(
                    text("SELECT * FROM orders WHERE id IN :order_ids").bindparams(
                        bindparam("order_ids", expanding=True)
                    ),
                    {"order_ids": order_ids},
                ).mappings().all()
                export["orders"] = [dict(r) for r in rows]
            else:
                rows = db.execute(
                    "SELECT * FROM orders WHERE customer_id = :uid",
                    {"uid": uid},
                ).mappings().all()
                export["orders"] = [dict(r) for r in rows]

            rows = db.execute(text("SELECT * FROM draft_orders WHERE customer_id = :uid"), {"uid": uid}).mappings().all()
            export["draft_orders"] = [dict(r) for r in rows]

            _where, params = _uid_patterns(uid, uid_hash)
            rows = db.execute(
                text(
                    "SELECT id, agent_name, valid_from, input_data, retrieved_context, agent_reasoning, "
                    "proposed_action, policy_version, approval_required, execution_status "
                    f"FROM decision_logs WHERE {_UID_WHERE_SQL} ORDER BY valid_from DESC"
                ),
                params,
            ).mappings().all()
            decisions = []
            decision_ids = []
            for r in rows:
                item = dict(r)
                decision_ids.append(item.get("id"))
                item["input_data"] = _safe_json(item.get("input_data"))
                item["retrieved_context"] = _safe_json(item.get("retrieved_context"))
                item["proposed_action"] = _safe_json(item.get("proposed_action"))
                if redact:
                    item["input_data"] = _redact_json(item["input_data"]) if isinstance(item["input_data"], (dict, list)) else item["input_data"]
                    item["retrieved_context"] = _redact_json(item["retrieved_context"]) if isinstance(item["retrieved_context"], (dict, list)) else item["retrieved_context"]
                    item["proposed_action"] = _redact_json(item["proposed_action"]) if isinstance(item["proposed_action"], (dict, list)) else item["proposed_action"]
                decisions.append(item)
            export["decision_logs"] = decisions

            if decision_ids:
                filtered_ids = [d for d in decision_ids if d]
                rows = db.execute(
                    text(
                        "SELECT id, decision_id, action, actor, metadata, created_at "
                        "FROM decision_audits WHERE decision_id IN :decision_ids ORDER BY created_at DESC"
                    ).bindparams(bindparam("decision_ids", expanding=True)),
                    {"decision_ids": filtered_ids},
                ).mappings().all()
                audits = []
                for r in rows:
                    item = dict(r)
                    item["metadata"] = _safe_json(item.get("metadata"))
                    if redact:
                        item["metadata"] = _redact_json(item["metadata"]) if isinstance(item["metadata"], (dict, list)) else item["metadata"]
                    audits.append(item)
                export["decision_audits"] = audits
        # Export ALL user-linked Redis keys (8 memory families + typed artifacts)
        # via the single inventory, not just summary/kv_state.
        try:
            from src.app.services.user_data_inventory import export_redis
            _session_mem = export_redis(redis, uid)
            if _session_mem:
                export["session_memory"] = _session_mem
        except Exception:
            pass
        sanitized, _hits = dlp_sanitize_export_value(export)
        return sanitized if isinstance(sanitized, dict) else {"export": sanitized}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.delete("/retention/purge")
def purge_retention(days: int = 90, role: str = Depends(require_role([ROLE_OWNER]))) -> Dict:
    """GDPR/Retention: Purge aged logs based on days threshold."""
    days = max(1, min(int(days or 90), 3650))
    deleted = {"security_events": 0, "iam_events": 0, "incidents": 0}
    try:
        with db_session() as db:
            try:
                res = db.execute(
                    "DELETE FROM security_events WHERE event_time < (CURRENT_TIMESTAMP - (:days || ' days')::interval)",
                    {"days": days},
                )
            except Exception:
                res = db.execute(
                    "DELETE FROM security_events WHERE event_time < datetime('now', :delta)",
                    {"delta": f"-{days} days"},
                )
            deleted["security_events"] = getattr(res, "rowcount", 0) or 0
            try:
                try:
                    res = db.execute(
                        "DELETE FROM iam_events WHERE event_time < (CURRENT_TIMESTAMP - (:days || ' days')::interval)",
                        {"days": days},
                    )
                except Exception:
                    res = db.execute(
                        "DELETE FROM iam_events WHERE event_time < datetime('now', :delta)",
                        {"delta": f"-{days} days"},
                    )
                deleted["iam_events"] = getattr(res, "rowcount", 0) or 0
            except Exception:
                deleted["iam_events"] = 0
            try:
                try:
                    res = db.execute(
                        "DELETE FROM incidents WHERE created_at < (CURRENT_TIMESTAMP - (:days || ' days')::interval)",
                        {"days": days},
                    )
                except Exception:
                    res = db.execute(
                        "DELETE FROM incidents WHERE created_at < datetime('now', :delta)",
                        {"delta": f"-{days} days"},
                    )
                deleted["incidents"] = getattr(res, "rowcount", 0) or 0
            except Exception:
                deleted["incidents"] = 0
            db.commit()
        return {"purged": True, "days": days, "deleted": deleted}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/optout/{uid}")
def opt_out_automated_decisions(uid: str, redis=Depends(get_redis), role: str = Depends(require_role([ROLE_OWNER, ROLE_MERCHANT]))) -> Dict:
    """GDPR Article 21: Opt-out of automated decision-making.

    Stores a session KV flag so downstream agents avoid automation and prefer human review.
    """
    try:
        mem = Memory(redis)
        ctx = mem.get_context(uid) or {}
        kv = ctx.get("kv") or {}
        kv["opt_out_automated_decisions"] = True
        mem.set_kv(uid, kv)
        return {"status": "opted_out", "uid": uid}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.delete("/optout/{uid}")
def clear_opt_out(uid: str, redis=Depends(get_redis), role: str = Depends(require_role([ROLE_OWNER, ROLE_MERCHANT]))) -> Dict:
    """Clear the opt-out preference to allow automated assistance again."""
    try:
        mem = Memory(redis)
        ctx = mem.get_context(uid) or {}
        kv = ctx.get("kv") or {}
        if "opt_out_automated_decisions" in kv:
            kv.pop("opt_out_automated_decisions", None)
        mem.set_kv(uid, kv)
        return {"status": "opt_out_cleared", "uid": uid}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/redact/{uid}")
def redact_user_data(uid: str, redis=Depends(get_redis), role: str = Depends(require_role([ROLE_OWNER]))) -> Dict:
    """Pseudonymize / redact PII in stored records for a user.

    This keeps auditability of decision events while removing sensitive
    personally-identifying data from payloads. Use when legal/ops require
    data minimization rather than full deletion.
    """
    uid_hash = hash_uid(uid)
    redacted = {"decision_logs": 0, "decision_audits": 0, "customers": 0}
    try:
        with db_session() as db:
            _where, params = _uid_patterns(uid, uid_hash)
            rows = db.execute(
                text(
                    "SELECT id, input_data, retrieved_context, proposed_action "
                    f"FROM decision_logs WHERE {_UID_WHERE_SQL}"
                ),
                params,
            ).fetchall()
            ids = []
            for r in rows:
                try:
                    _id = r[0]
                    ids.append(_id)
                    inp = _safe_json(r[1])
                    rc = _safe_json(r[2])
                    pa = _safe_json(r[3])
                    new_inp = _redact_json(inp) if isinstance(inp, (dict, list)) else inp
                    new_rc = _redact_json(rc) if isinstance(rc, (dict, list)) else rc
                    new_pa = _redact_json(pa) if isinstance(pa, (dict, list)) else pa
                    db.execute(text("UPDATE decision_logs SET input_data = :inp, retrieved_context = :rc, proposed_action = :pa WHERE id = :id"), {"inp": json.dumps(new_inp, ensure_ascii=False), "rc": json.dumps(new_rc, ensure_ascii=False), "pa": json.dumps(new_pa, ensure_ascii=False), "id": _id})
                except Exception:
                    pass
            redacted["decision_logs"] = len(ids)
            # redact decision_audits metadata
            if ids:
                rows2 = db.execute(
                    text("SELECT id, metadata FROM decision_audits WHERE decision_id IN :decision_ids").bindparams(
                        bindparam("decision_ids", expanding=True)
                    ),
                    {"decision_ids": ids},
                ).fetchall()
                cnt = 0
                for r2 in rows2:
                    try:
                        aid = r2[0]
                        meta = _safe_json(r2[1])
                        new_meta = _redact_json(meta) if isinstance(meta, (dict, list)) else meta
                        db.execute(text("UPDATE decision_audits SET metadata = :m WHERE id = :id"), {"m": json.dumps(new_meta, ensure_ascii=False), "id": aid})
                        cnt += 1
                    except Exception:
                        pass
                redacted["decision_audits"] = cnt
            # pseudonymize customers row for strict minimization
            try:
                res = db.execute(text("UPDATE customers SET email = 'REDACTED', phone = NULL, first_name = 'REDACTED', last_name = NULL WHERE id = :uid"), {"uid": uid})
                redacted["customers"] = getattr(res, "rowcount", 0) or 0
            except Exception:
                redacted["customers"] = 0
            db.commit()
        try:
            from src.app.services.user_data_inventory import redact_redis
            redacted["session_memory"] = redact_redis(redis, uid)
        except Exception:
            pass
        return {"status": "redacted", "uid": uid, "uid_hash": uid_hash, "redacted_counts": redacted}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
