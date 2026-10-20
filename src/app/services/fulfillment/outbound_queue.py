"""Durable supplier-message attempts with exact payload and approval binding.

Known pre-send failures have bounded retries. Uncertain delivery and expired worker
claims require reconciliation; idempotency headers alone do not prevent duplicate
SMTP effects. Default transports contain real delivery pending identity integration.
Caller-injected adapters remain an internal boundary, not authenticated HTTP proof.
"""
from __future__ import annotations

import logging
import os
import uuid
from time import monotonic
from typing import Any, Dict, List, Optional

from sqlalchemy import text

logger = logging.getLogger("shopsquire.outbound_queue")

_DDL = """
CREATE TABLE IF NOT EXISTS outbound_message (
    id               TEXT PRIMARY KEY,
    tenant_id        TEXT,
    case_id          TEXT,
    recipient        TEXT,
    subject          TEXT,
    body             TEXT,
    idempotency_key  TEXT,
    status           TEXT DEFAULT 'pending',   -- pending | sending | sent | dead_letter
    attempts         INTEGER DEFAULT 0,
    max_attempts     INTEGER DEFAULT 5,
    next_attempt_at  TEXT,
    provider_ref     TEXT,
    ack_status       TEXT DEFAULT 'awaiting',  -- awaiting | acked  (EDI 855)
    acked_at         TEXT,
    ack_reference    TEXT,
    last_error       TEXT,
    actor_type       TEXT,                     -- the approved transition intent, replayed on deferred delivery
    actor_id         TEXT,
    transition_event TEXT,
    channel          TEXT DEFAULT 'email',
    schedule_reason  TEXT,
    sla_clock        TEXT DEFAULT 'unknown',
    transport_eligible INTEGER DEFAULT 1,
    created_at       TEXT,
    updated_at       TEXT,
    effect_digest    TEXT,
    permit_expires_at TEXT,
    permit_revoked_at TEXT,
    person_approval_id TEXT,
    UNIQUE (tenant_id, idempotency_key)
)
"""

# Age after which an unfinished claim is held for reconciliation, without resend.
def _stale_claim_seconds() -> int:
    return int(os.getenv("OUTBOUND_STALE_CLAIM_SEC", "300") or 300)


def _now_iso(now_iso: Optional[str]) -> str:
    """UTC without an offset, preserving subsecond precision for lexical due checks.

    Historical naive queue timestamps represent UTC. Convert aware inputs to that
    same clock; comparing ISO strings with different offsets can dispatch early.
    """
    from datetime import datetime, timezone
    stamp = datetime.fromisoformat(str(now_iso).replace('Z', '+00:00')) if now_iso else datetime.now(timezone.utc)
    if stamp.tzinfo is not None:
        stamp = stamp.astimezone(timezone.utc).replace(tzinfo=None)
    return stamp.isoformat()


def _plus_seconds(now_iso: str, seconds: int) -> str:
    from datetime import datetime, timedelta
    base = datetime.fromisoformat(_now_iso(now_iso))
    return (base + timedelta(seconds=float(seconds))).isoformat()


def _backoff_seconds(attempts: int) -> int:
    """Exponential backoff: base * 2^attempts, capped. attempts is the count AFTER this failure."""
    base = int(os.getenv("OUTBOUND_RETRY_BASE_SEC", "60") or 60)
    cap = int(os.getenv("OUTBOUND_RETRY_CAP_SEC", "3600") or 3600)
    return min(cap, base * (2 ** max(0, int(attempts) - 1)))


def _project_lifecycle(
    db, *, tenant_id: str, message_id: str, case_id: str, recipient: str,
    subject: str, body: str, state: str, idempotency_key: str,
    actor_type: str, actor_id: str = "", reason: str = "",
    grounding_materials: Optional[List[Dict[str, Any]]] = None,
    party_ref: Optional[str] = None,
) -> None:
    try:
        from src.app.services.communication_lifecycle import (
            append_transition,
            register_approved_grounding,
        )
        from src.app.services.communication_observations import record_message_observation
        grounding_refs: List[str] = []
        material_claims: List[Dict[str, str]] = []
        for material in grounding_materials or []:
            if not isinstance(material, dict):
                continue
            source_ref = str(
                material.get("source_ref") or material.get("evidence_id") or ""
            ).strip()
            content = str(
                material.get("content") or material.get("summary") or ""
            ).strip()
            if not source_ref or not content:
                continue
            grounding_ref = register_approved_grounding(
                db,
                tenant_id=tenant_id,
                grounding_type=str(material.get("grounding_type") or "fact"),
                source_ref=source_ref,
                source_version=str(material.get("source_version") or "1"),
                content=content,
                approved_by=actor_id or actor_type or "governed_send_boundary",
            )
            grounding_refs.append(grounding_ref)
            material_claims.append(
                {"text": content, "grounding_ref": grounding_ref}
            )
        observation = record_message_observation(
            db=db, tenant_id=tenant_id, party_type="supplier", direction="outbound",
            channel="outbound_queue", provider_message_id=message_id,
            purpose="supplier_delivery", consent_status="not_required",
            security_status="accepted",
            sanitized_payload={
                "recipient": recipient, "subject": subject, "body": body,
                "material_claims": material_claims,
            },
            case_ref=case_id,
            party_ref=party_ref,
        )
        observation_id = str(observation["id"])
        current = db.execute(text(
            "SELECT state FROM communication_lifecycle_event "
            "WHERE tenant_id=:t AND observation_id=:o ORDER BY sequence_no DESC LIMIT 1"
        ), {"t": tenant_id, "o": observation_id}).scalar()
        if state == "queued" and current == "proposed":
            append_transition(
                db, tenant_id=tenant_id, observation_id=observation_id,
                state="approved", idempotency_key=f"{idempotency_key}:approved",
                actor_type=actor_type or "approved_boundary", actor_id=actor_id,
                reason="existing governed send approval",
                grounding_refs=grounding_refs,
            )
        append_transition(
            db, tenant_id=tenant_id, observation_id=observation_id,
            state=state, idempotency_key=f"{idempotency_key}:{state}",
            actor_type=actor_type or "worker", actor_id=actor_id, reason=reason,
            grounding_refs=grounding_refs,
        )
    except Exception as exc:
        logger.warning(
            "communication lifecycle projection failed message_id=%s state=%s: %s",
            message_id, state, exc,
        )
        if str(os.getenv("APP_ENV") or "").strip().lower() in {"prod", "production", "staging"}:
            raise


def enqueue(db, *, case_id: str, recipient: str, subject: str, body: str, idempotency_key: str,
            max_attempts: int = 5, tenant_id: str = "default", actor_type: str = "", actor_id: str = "",
            transition_event: str = "", now_iso: Optional[str] = None,
            grounding_materials: Optional[List[Dict[str, Any]]] = None,
            party_ref: Optional[str] = None, channel: str = "email",
            response_expectation: Optional[Dict[str, Any]] = None, person_approval_id: str | None = None) -> Dict[str, Any]:
    """Durably enqueue an outbound supplier message. IDEMPOTENT on (tenant, idempotency_key) — a retried
    enqueue of the same content_hash returns the existing row (deduped), never a second send. pending +
    due now. ``actor_type``/``actor_id``/``transition_event`` persist the already-approved workflow intent so a
    DEFERRED delivery (background processor) can replay exactly that transition — never inventing a new one.
    Returns {message_id, status, deduped}."""
    if db is None or not idempotency_key:
        return {"message_id": None, "status": "skipped", "deduped": False}
    ts = _now_iso(now_iso)
    from src.app.services.fulfillment.effect_contract import effect_digest
    binding = effect_digest(tenant_id=tenant_id, case_id=case_id, recipient=recipient,
        subject=subject, body=body, channel=channel, actor_type=actor_type, actor_id=actor_id,
        transition_event=transition_event, idempotency_key=idempotency_key,person_approval_id=person_approval_id)
    if person_approval_id:
        from src.app.services.fulfillment.person_approval import validate
        validate(db,tenant_id=tenant_id,approval_id=person_approval_id,digest=binding,now=ts)
    from src.app.services.supplier_contact_schedule import decide_contact_schedule
    schedule = decide_contact_schedule(
        channel=channel, expectation=response_expectation, submitted_at=ts,
    )
    try:
        existing = db.execute(text("SELECT id, status, effect_digest FROM outbound_message WHERE tenant_id=:t AND idempotency_key=:k LIMIT 1"),
                              {"t": tenant_id, "k": idempotency_key}).fetchone()
        if existing:
            if existing[2] != binding:
                return {"message_id": existing[0], "status": "effect_conflict", "deduped": False}
            return {"message_id": existing[0], "status": existing[1], "deduped": True}
        mid = f"out-{uuid.uuid4().hex[:12]}"
        db.execute(text(
            "INSERT INTO outbound_message (id, tenant_id, case_id, recipient, subject, body, idempotency_key, "
            "status, attempts, max_attempts, next_attempt_at, ack_status, actor_type, actor_id, transition_event, "
            "channel, schedule_reason, sla_clock, transport_eligible, "
            "created_at, updated_at, effect_digest, permit_expires_at,person_approval_id) "
            "VALUES (:i,:t,:c,:r,:s,:b,:k,:status,0,:m,:n,'awaiting',:at,:ai,:te,:channel,:reason,:sla,:eligible,:ts,:ts,:digest,:expiry,:person)"),
            {"i": mid, "t": tenant_id, "c": case_id, "r": recipient, "s": subject, "b": body,
             "digest": binding, "expiry": _plus_seconds(ts, 86400), "person":person_approval_id,
             "k": idempotency_key, "m": int(max_attempts),
             "n": _now_iso(schedule.not_before) if schedule.not_before else None,
             "status": schedule.queue_state, "at": actor_type, "ai": actor_id,
             "te": transition_event, "channel": schedule.channel, "reason": schedule.reason,
             "sla": schedule.sla_clock, "eligible": 1 if schedule.transport_eligible else 0, "ts": ts})
        _project_lifecycle(
            db, tenant_id=tenant_id, message_id=mid, case_id=case_id,
            recipient=recipient, subject=subject, body=body, state="queued",
            idempotency_key=idempotency_key, actor_type=actor_type, actor_id=actor_id,
            grounding_materials=grounding_materials,
            party_ref=party_ref,
        )
        db.commit()
        return {"message_id": mid, "status": schedule.queue_state, "deduped": False,
                "channel": schedule.channel, "not_before": schedule.not_before,
                "schedule_reason": schedule.reason, "sla_clock": schedule.sla_clock}
    except Exception as exc:
        logger.debug("outbound enqueue failed for %s: %s", case_id, exc)
        try:
            db.rollback()
        except Exception:
            pass
        return {"message_id": None, "status": "error", "deduped": False}


def _reclaim_stale(db, *, tenant_id: str, ts: str) -> None:
    """Quarantine uncertain delivery after a worker dies; never infer provider deduplication."""
    cutoff = _plus_seconds(ts, -_stale_claim_seconds())
    age = _utc_sql(db, 'updated_at') + ' < ' + _utc_sql(db, ':cut')
    db.execute(text("UPDATE outbound_message SET status='reconciliation_required', "
                    "last_error='delivery_outcome_unknown', updated_at=:ts WHERE tenant_id=:t "
                    "AND status='sending' AND " + age), {"ts": ts, "t": tenant_id, "cut": cutoff})


def _utc_sql(db, expression):
    """Compare existing ISO timestamps as instants, including old offset rows.

    Expressions are internal column names or bind placeholders. Historical naive
    timestamps mean UTC even when the PostgreSQL connection timezone differs.
    """
    dialect = db.get_bind().dialect.name
    if dialect == 'sqlite':
        return f'julianday({expression})'
    if dialect == 'postgresql':
        return (f"(CASE WHEN {expression} ~ '(Z|[+-][0-9]{{2}}:[0-9]{{2}})$' "
                f"THEN CAST({expression} AS TIMESTAMPTZ) "
                f"ELSE CAST({expression} AS TIMESTAMP) AT TIME ZONE 'UTC' END)")
    raise ValueError('outbound_timestamp_dialect_not_supported')


def _attempt_delivery(transport, **payload):
    """A raised error cannot prove that the provider did not accept the effect."""
    try:
        result=transport.send(**payload)
        status=getattr(result,'status','unknown')
        return (status if status in ('sent','failed') else 'unknown',
                getattr(result,'provider_ref','') or '',getattr(result,'detail','') or '')
    except Exception as exc:
        return 'unknown','',f'{type(exc).__name__}: {exc}'[:200]


_CLAIM_WHERE = (
    "tenant_id=:claim_tenant AND id=:claim_id AND status='sending' "
    "AND attempts=:claim_attempt AND effect_digest=:claim_digest"
)


def _update_claim(db, claim, assignments, values):
    """Internal SQL assignments; a late attempt cannot settle a newer state."""
    return db.execute(text('UPDATE outbound_message SET ' + assignments + ' WHERE ' + _CLAIM_WHERE),
                      {**claim, **values}).rowcount == 1


def _delivery_update(status, provider_ref, detail, ts, attempts, max_attempts):
    if status == 'sent':
        return "status='sent',provider_ref=:p,last_error=NULL,updated_at=:ts", {'p': provider_ref, 'ts': ts}
    if status == 'unknown':
        return ("status='reconciliation_required',last_error=:e,updated_at=:ts",
                {'e': 'delivery_outcome_unknown:' + detail, 'ts': ts})
    if attempts >= max_attempts:
        return "status='dead_letter',last_error=:e,updated_at=:ts", {'e': detail, 'ts': ts}
    return ("status='pending',next_attempt_at=:n,last_error=:e,updated_at=:ts",
            {'n': _plus_seconds(ts, _backoff_seconds(attempts)), 'e': detail, 'ts': ts})


def process_pending(db, *, transport: Optional[Any] = None, tenant_id: str = "default",
                    limit: int = 50, only_key: str = "", now_iso: Optional[str] = None) -> Dict[str, Any]:
    """Attempt every DUE pending message once. Each row is ATOMICALLY CLAIMED (pending→sending) before transmit
    so two workers can never both send it (the loser's claim affects 0 rows and is skipped); the result is
    committed PER ROW so a crash after transmit leaves the row 'sending' (recoverable, NOT re-sent) rather than
    'pending' (which would re-send). On success → sent (+ provider_ref); on failure → backoff retry, or
    dead_letter at max_attempts. Returns {processed, sent, retried, dead_lettered, sent_rows} where sent_rows
    carries the approved transition intent for a workflow-aware caller to replay (fixes deferred-send stranding).
    ``only_key`` scopes the drive to a single message (the synchronous send path)."""
    if db is None:
        return {"processed": 0, "sent": 0, "retried": 0, "dead_lettered": 0, "sent_rows": []}
    tx = transport or _default_transport()
    ts = _now_iso(now_iso)
    started = monotonic()
    out: Dict[str, Any] = {"processed": 0, "sent": 0, "retried": 0, "dead_lettered": 0, "sent_rows": []}
    try:
        _reclaim_stale(db, tenant_id=tenant_id, ts=ts)
        due = _utc_sql(db, 'next_attempt_at') + ' <= ' + _utc_sql(db, ':ts')
        sql = ("SELECT id, case_id, recipient, subject, body, idempotency_key, attempts, max_attempts, "
               "actor_type, actor_id, transition_event, effect_digest, permit_expires_at, permit_revoked_at,person_approval_id FROM outbound_message WHERE tenant_id=:t AND status IN ('pending','scheduled') "
               "AND channel='email' AND transport_eligible=1 "
               "AND (next_attempt_at IS NULL OR " + due + ") ")
        params: Dict[str, Any] = {"t": tenant_id, "ts": ts, "lim": int(limit)}
        if only_key:
            sql += "AND idempotency_key=:k "
            params["k"] = only_key
        sql += "ORDER BY created_at ASC LIMIT :lim"
        rows = db.execute(text(sql), params).fetchall()
        db.commit()
    except Exception as exc:
        logger.debug("process_pending query failed: %s", exc)
        out["error"] = f"{type(exc).__name__}: {exc}"
        return out
    for r in (rows or []):
        mid, case_id, recipient, subject, body, idem, attempts, max_attempts, a_type, a_id, t_event, binding, expiry, revoked, person = r
        from src.app.services.fulfillment.effect_contract import effect_digest, permit_current
        current_binding = effect_digest(tenant_id=tenant_id, case_id=case_id, recipient=recipient,
            subject=subject, body=body, channel="email", actor_type=a_type or "", actor_id=a_id or "",
            transition_event=t_event or "", idempotency_key=idem,person_approval_id=person)
        from src.app.services.fulfillment.person_approval import dispatch_current
        dispatch_time = _plus_seconds(ts, max(0, monotonic() - started))
        if binding != current_binding or not permit_current(expiry, revoked, dispatch_time) or not dispatch_current(db,tenant_id,person,binding,dispatch_time):
            db.execute(text("UPDATE outbound_message SET status='blocked_authority', last_error=:e "
                            "WHERE tenant_id=:t AND id=:i AND status IN ('pending','scheduled')"),
                       {"e": "effect_binding_or_permit_invalid", "t": tenant_id, "i": mid})
            db.commit()
            out["blocked_authority"] = out.get("blocked_authority", 0) + 1
            continue
        # ATOMIC CLAIM: only the worker whose UPDATE flips pending→sending may transmit (rowcount guard).
        try:
            claim = db.execute(text("UPDATE outbound_message SET status='sending', attempts=attempts+1, "
                                    "updated_at=:ts WHERE id=:i AND tenant_id=:t AND effect_digest=:digest "
                                    "AND recipient=:recipient AND subject=:subject AND body=:body "
                                    "AND case_id=:case AND channel='email' AND transport_eligible=1 "
                                    "AND COALESCE(actor_type,'')=:actor_type AND COALESCE(actor_id,'')=:actor_id "
                                    "AND COALESCE(transition_event,'')=:event AND permit_expires_at=:expiry "
                                    "AND COALESCE(person_approval_id,'')=:person "
                                    "AND permit_revoked_at IS NULL AND attempts=:prior_attempts "
                                    "AND status IN ('pending','scheduled')"),
                               {"ts": ts, "i": mid, "t": tenant_id, "digest": binding,
                                "recipient": recipient, "subject": subject, "body": body, "case": case_id,
                                "actor_type": a_type or "", "actor_id": a_id or "", "event": t_event or "",
                                "expiry": expiry,"person":person or '', 'prior_attempts': int(attempts or 0)})
            db.commit()
        except Exception as exc:
            logger.warning("outbound claim failed for %s: %s", mid, exc)
            try:
                db.rollback()
            except Exception:
                pass
            continue
        if getattr(claim, "rowcount", 0) != 1:
            continue  # another worker claimed it first
        out["processed"] += 1
        new_attempts = int(attempts or 0) + 1
        claim_owner = dict(claim_tenant=tenant_id, claim_id=mid,
                           claim_attempt=new_attempts, claim_digest=binding)
        # OUTBOUND INTEGRITY GATE: scan the drafted content right before it leaves so the platform
        # never RELAYS a poisoned payload or LEAKS a secret to a supplier (becoming a threat vector).
        # A 'block' quarantines the row (never transmitted); the finding is traced for the
        # Procurement tab so bounded-autonomy safety is visible.
        _integrity = {"action": "allow", "findings": [], "categories": []}
        try:
            from src.app.services.fulfillment.outbound_integrity import scan_outbound_supplier_message
            _integrity = scan_outbound_supplier_message(subject, body, recipient=recipient)
        except Exception:
            _integrity = {"action": "block", "findings": ["integrity_scanner_unavailable"], "categories": []}
        if not isinstance(_integrity, dict) or _integrity.get('action') != 'allow':
            if not isinstance(_integrity, dict):
                _integrity = {'findings': ['integrity_result_invalid'], 'categories': []}
            try:
                if not _update_claim(db, claim_owner,
                        "status='blocked_content', last_error=:e, updated_at=:ts",
                        {'e': ('integrity:' + ','.join(_integrity.get('findings') or []))[:200], 'ts': ts}):
                    db.rollback()
                    out['settlement_conflicts'] = out.get('settlement_conflicts', 0) + 1
                    continue
                db.commit()
                _project_lifecycle(
                    db, tenant_id=tenant_id, message_id=mid, case_id=case_id,
                    recipient=recipient, subject=subject, body=body, state="quarantined",
                    idempotency_key=f"{idem}:integrity", actor_type="security",
                    reason="outbound_integrity_block",
                )
                db.commit()
                from src.app.services.decision_log import log_trace_event as _lte
                _lte(trace_id=f"case:{case_id}", event_type="outbound_integrity_block", source_type="agent",
                     source_id="Outbound_Integrity_Guard", target_type="supplier_message", target_id=mid,
                     payload={"action": "block", "findings": _integrity.get("findings"),
                              "categories": _integrity.get("categories"),
                              "recipient_domain": (str(recipient).split("@", 1)[1].lower() if "@" in str(recipient) else None)})
            except Exception as _blk_exc:
                logger.debug("integrity block record failed for %s: %s", mid, _blk_exc)
            out.setdefault("blocked_content", 0)
            out["blocked_content"] += 1
            continue  # never transmit a blocked message
        dispatch_time = _plus_seconds(ts, max(0, monotonic() - started))
        still_owned = db.execute(text('SELECT 1 FROM outbound_message WHERE ' + _CLAIM_WHERE +
                                      ' AND permit_revoked_at IS NULL AND permit_expires_at=:expiry'),
                                 {**claim_owner, 'expiry': expiry}).scalar()
        if not still_owned:
            db.rollback()
            out['settlement_conflicts'] = out.get('settlement_conflicts', 0) + 1
            continue
        if not permit_current(expiry, revoked, dispatch_time) or not dispatch_current(db,tenant_id,person,binding,dispatch_time):
            _update_claim(db, claim_owner, "status='blocked_authority',last_error='person_approval_invalid'", {})
            db.commit()
            out['blocked_authority']=out.get('blocked_authority',0)+1
            continue
        status, provider_ref, detail = _attempt_delivery(
            tx,to=recipient,subject=subject,body=body,idempotency_key=str(idem or ''))
        try:
            assignments, values = _delivery_update(status, provider_ref, detail, ts,
                                                   new_attempts, int(max_attempts or 5))
            if not _update_claim(db, claim_owner, assignments, values):
                db.rollback()
                out['settlement_conflicts'] = out.get('settlement_conflicts', 0) + 1
                continue
            if status == "sent":
                _project_lifecycle(
                    db, tenant_id=tenant_id, message_id=mid, case_id=case_id,
                    recipient=recipient, subject=subject, body=body, state="submitted",
                    idempotency_key=str(idem or mid), actor_type="worker",
                    reason=f"provider_ref:{provider_ref}",
                )
                db.commit()
                out["sent"] += 1
                out["sent_rows"].append({"case_id": case_id, "content_hash": idem, "provider_ref": provider_ref,
                                         "actor_type": a_type or "", "actor_id": a_id or "",
                                         "transition_event": t_event or ""})
            elif status == 'unknown':
                db.commit()
                out['reconciliation_required']=out.get('reconciliation_required',0)+1
            elif new_attempts >= int(max_attempts or 5):
                _project_lifecycle(
                    db, tenant_id=tenant_id, message_id=mid, case_id=case_id,
                    recipient=recipient, subject=subject, body=body, state="failed",
                    idempotency_key=f"{idem}:dead-letter", actor_type="worker", reason=detail,
                )
                db.commit()
                out["dead_lettered"] += 1
            else:
                db.commit()
                out["retried"] += 1
        except Exception as exc:
            # Commit of the RESULT failed. The row stays 'sending' (not 'pending'), so it is NOT re-sent on the
            # next pass — only reclaimed after the stale window. Surface loudly; never swallow silently.
            logger.error("outbound result-commit failed for %s (transport status=%s) — row left 'sending' for "
                         "stale-reclaim: %s", mid, status, exc)
            try:
                db.rollback()
            except Exception:
                pass
    return out


def get_by_key(db, *, idempotency_key: str, tenant_id: str = "default") -> Dict[str, Any]:
    """Read one message's reliability state by content_hash — {status, provider_ref, attempts, ack_status}."""
    if db is None or not idempotency_key:
        return {}
    try:
        r = db.execute(text("SELECT status, provider_ref, attempts, ack_status, last_error, acked_at FROM outbound_message "
                            "WHERE tenant_id=:t AND idempotency_key=:k LIMIT 1"),
                       {"t": tenant_id, "k": idempotency_key}).fetchone()
        if not r:
            return {}
        from src.app.services.fulfillment.effect_contract import completion_status
        return {"status": r[0], "provider_ref": r[1] or "", "attempts": int(r[2] or 0),
                "ack_status": r[3], "last_error": r[4] or "",
                "completion_status": completion_status(status=r[0], provider_ref=r[1],
                    ack_status=r[3], acked_at=r[5])}
    except Exception:
        return {}


def send_now(db, *, case_id: str, recipient: str, subject: str, body: str, idempotency_key: str,
             transport: Optional[Any] = None, max_attempts: int = 5, tenant_id: str = "default",
             actor_type: str = "", actor_id: str = "", transition_event: str = "",
             now_iso: Optional[str] = None,
             grounding_materials: Optional[List[Dict[str, Any]]] = None,
             party_ref: Optional[str] = None, channel: str = "email",
             response_expectation: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Synchronous RELIABLE send for the GATE-2 path: durably enqueue (idempotent on content_hash) then attempt
    THIS message once. Returns {status, provider_ref, detail}: 'sent' (caller transitions now), or 'pending'
    (transient failure — durably retryable by the background processor, the human can re-dispatch), or
    'dead_letter'. The actor/event are persisted so a DEFERRED delivery replays the SAME approved transition.
    Preserves the human-only send invariant: it only sends what the caller already approved, and a re-dispatch
    of the same content_hash never double-sends (deduped)."""
    enqueued = enqueue(db, case_id=case_id, recipient=recipient, subject=subject, body=body, idempotency_key=idempotency_key,
            max_attempts=max_attempts, tenant_id=tenant_id, actor_type=actor_type, actor_id=actor_id,
            transition_event=transition_event, now_iso=now_iso,
            grounding_materials=grounding_materials, party_ref=party_ref,
            channel=channel, response_expectation=response_expectation)
    if enqueued.get("status") == "effect_conflict":
        return {"status": "failed", "detail": "effect_conflict", "provider_ref": ""}
    existing = get_by_key(db, idempotency_key=idempotency_key, tenant_id=tenant_id)
    if existing.get("status") == "sent":  # idempotent re-dispatch of an already-delivered message
        return {"status": "sent", "provider_ref": existing.get("provider_ref", ""), "detail": "deduped"}
    if existing.get("status") == "sending":  # claimed by a concurrent worker — do NOT re-send; let it settle
        return {"status": "pending", "provider_ref": "", "detail": "in_flight"}
    process_pending(db, transport=transport, tenant_id=tenant_id, only_key=idempotency_key, now_iso=now_iso)
    row = get_by_key(db, idempotency_key=idempotency_key, tenant_id=tenant_id)
    return {"status": row.get("status", "pending"), "provider_ref": row.get("provider_ref", ""),
            "detail": row.get("last_error", "")}


def revoke_pending_permit(db, *, tenant_id: str, idempotency_key: str, now_iso=None) -> bool:
    """Withdraw an undispatched grant. In-flight effects require reconciliation."""
    result = db.execute(text(
        "UPDATE outbound_message SET permit_revoked_at=:now, status='blocked_authority', "
        "last_error='permit_revoked' WHERE tenant_id=:t AND idempotency_key=:k "
        "AND status IN ('pending','scheduled')"
    ), {"now": _now_iso(now_iso), "t": tenant_id, "k": idempotency_key})
    db.commit()
    return result.rowcount == 1


def record_ack(db, *, idempotency_key: str, ack_ref: str = "", case_id: str = "", tenant_id: str = "default",
               now_iso: Optional[str] = None) -> Dict[str, Any]:
    """Record the supplier's acknowledgement (EDI 855) — but ONLY for a message that was actually SENT (you
    cannot acknowledge an unsent draft), and ONLY when the optional ``case_id`` matches the row (so an ack can't
    be routed to the wrong case). Returns {acked, message_id, reason}."""
    if db is None or not idempotency_key:
        return {"acked": False, "message_id": None, "reason": "no_key"}
    ts = _now_iso(now_iso)
    try:
        row = db.execute(text("SELECT id, status, case_id FROM outbound_message WHERE tenant_id=:t "
                              "AND idempotency_key=:k LIMIT 1"), {"t": tenant_id, "k": idempotency_key}).fetchone()
        if not row:
            return {"acked": False, "message_id": None, "reason": "not_found"}
        if row[1] != "sent":
            return {"acked": False, "message_id": row[0], "reason": f"not_sent:{row[1]}"}
        if case_id and str(row[2] or "") != str(case_id):
            return {"acked": False, "message_id": row[0], "reason": "case_mismatch"}
        db.execute(text("UPDATE outbound_message SET ack_status='acked', acked_at=:ts, ack_reference=:ar, "
                        "updated_at=:ts WHERE id=:i AND status='sent'"),
                   {"ts": ts, "ar": ack_ref, "i": row[0]})
        db.commit()
        return {"acked": True, "message_id": row[0], "reason": "ok"}
    except Exception as exc:
        logger.debug("record_ack failed for %s: %s", idempotency_key, exc)
        return {"acked": False, "message_id": None, "reason": "error"}


def queue_status(db, *, tenant_id: str = "default") -> Dict[str, Any]:
    """Counts by status + unacknowledged-sent count — the operator/observability view."""
    if db is None:
        return {}
    try:
        rows = db.execute(text("SELECT status, COUNT(*) FROM outbound_message WHERE tenant_id=:t GROUP BY status"),
                          {"t": tenant_id}).fetchall()
        by_status = {str(r[0]): int(r[1]) for r in (rows or [])}
        unacked = db.execute(text("SELECT COUNT(*) FROM outbound_message WHERE tenant_id=:t AND status='sent' "
                                  "AND ack_status<>'acked'"), {"t": tenant_id}).fetchone()
        return {"by_status": by_status, "unacknowledged_sent": int((unacked or [0])[0] or 0)}
    except Exception:
        return {}


def dead_letters(db, *, tenant_id: str = "default", limit: int = 50) -> List[Dict[str, Any]]:
    """The messages that exhausted their retries — the operator triage queue."""
    if db is None:
        return []
    try:
        rows = db.execute(text("SELECT id, case_id, recipient, subject, attempts, last_error, updated_at "
                               "FROM outbound_message WHERE tenant_id=:t AND status='dead_letter' "
                               "ORDER BY updated_at DESC LIMIT :lim"), {"t": tenant_id, "lim": int(limit)}).fetchall()
        return [{"id": r[0], "case_id": r[1], "recipient": r[2], "subject": r[3], "attempts": int(r[4] or 0),
                 "last_error": r[5] or "", "updated_at": r[6]} for r in (rows or [])]
    except Exception:
        return []


def _default_transport() -> Any:
    """Share the foreground send boundary, including the independent-approval hold."""
    from src.app.services.fulfillment.transport import get_transport
    return get_transport()
