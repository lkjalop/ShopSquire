"""Fulfilment workflow (agnostic CORE) — the single runtime chokepoint every command passes through.

transition() is where the domain contract (domain.py) meets durable state (repository.py): EVERY
command runs through it, and it —
  1. loads the case's current state (unknown → not_found);
  2. enforces the actor guard via domain.can_fire (illegal/disallowed → rejected, never applied);
  3. on a confidence-gated transition, authorizes through the adaptive-action gate (deny → rejected);
  4. writes a new BITEMPORAL version (SCD-2 supersede);
  5. emits a decision-trace event with the actor + evidence (the audit narrative);
  6. returns the new state.

Idempotency: a command carrying an idempotency_key that was already applied returns the prior result
instead of double-applying (a double-clicked send/PO is safe). The API maps a rejected TransitionResult
to 409/403; a successful one to the new case view. Best-effort + never raises into the caller.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from src.app.services.fulfillment import domain, repository
from src.app.services.fulfillment.domain import Actor, FAILURE_STATES, FulfillmentState

# confidence-gated events → the adaptive-action gate's action type
_GATE_ACTION = {
    "external_message_drafted": "supplier_contact_draft",
    "fulfillment_options_generated": "fulfillment_options",
    "approval_granted_autonomous": "supplier_rfq_send",  # WS-C: autonomous approval → action-gate authorizes
}


@dataclass(frozen=True)
class TransitionResult:
    ok: bool
    case_id: str
    state: Optional[str]            # the resulting (or current, on reject) state
    reason: str                    # ok | idempotent_replay | not_found | illegal_transition |
                                   # actor_not_permitted | terminal_state | gate:<reason>
    version_id: Optional[str] = None
    http_status: int = 200         # 200 ok · 404 not_found · 409 illegal/terminal · 403 actor/gate


def _http_for(reason: str) -> int:
    if reason in ("ok", "idempotent_replay"):
        return 200
    if reason == "not_found":
        return 404
    if reason in ("actor_not_permitted",) or reason.startswith("gate:"):
        return 403
    return 409  # illegal_transition / terminal_state


def open_case(db, *, buyer_uid_hash: Optional[str], source_trace_id: Optional[str], requested_by: str,
              tenant_id: str = "default", now_iso: Optional[str] = None,
              state_json: Optional[Dict[str, Any]] = None) -> Optional[str]:
    """Open a case at NEW. Returns the case_id."""
    return repository.create_case(db, initial_state=FulfillmentState.NEW.value, buyer_uid_hash=buyer_uid_hash,
                                  source_trace_id=source_trace_id, requested_by=requested_by,
                                  tenant_id=tenant_id, now_iso=now_iso, state_json=state_json)


def current_state(db, case_id: str, tenant_id: str = "default") -> Optional[FulfillmentState]:
    cur = repository.current_version(db, case_id, tenant_id)
    if cur is None:
        return None
    try:
        return FulfillmentState(cur.state)
    except Exception:
        return None


def _emit_trace(*, trace_id, event, actor: Actor, case_id, evidence, reason_code, valid_from):
    try:
        from src.app.services.decision_log import log_trace_event
        log_trace_event(
            trace_id=trace_id, event_type=event, source_type=actor.type.value, source_id=actor.id,
            target_type="fulfillment_case", target_id=case_id,
            payload={"reason_code": reason_code, "evidence": evidence or {},
                     "bitemporal": {"valid_from": valid_from}},
        )
    except Exception:
        return  # the trace is the narrative; a logging failure must not roll back a committed transition


def transition(
    db,
    *,
    case_id: str,
    event: str,
    actor: Actor,
    reason_code: str = "",
    evidence: Optional[Dict[str, Any]] = None,
    state_patch: Optional[Dict[str, Any]] = None,
    confidence: float = 1.0,
    idempotency_key: Optional[str] = None,
    tenant_id: str = "default",
    now_iso: Optional[str] = None,
    trace_id: Optional[str] = None,
) -> TransitionResult:
    """Apply one command. The ONLY way a case changes state."""
    if db is None or not case_id:
        return TransitionResult(False, case_id or "", None, "not_found", http_status=404)
    try:
        # idempotent replay — return the prior result without re-applying
        if idempotency_key:
            existing = repository.find_idempotent_version(db, case_id, event, idempotency_key, tenant_id)
            if existing:
                st = current_state(db, case_id, tenant_id)
                return TransitionResult(True, case_id, st.value if st else None, "idempotent_replay",
                                        version_id=existing)

        cur = repository.current_version(db, case_id, tenant_id)
        if cur is None:
            return TransitionResult(False, case_id, None, "not_found", http_status=404)
        try:
            state = FulfillmentState(cur.state)
        except Exception:
            return TransitionResult(False, case_id, cur.state, "not_found", http_status=404)

        # 1. actor + legality guard
        ok, why = domain.can_fire(state, event, actor)
        if not ok:
            return TransitionResult(False, case_id, state.value, why, http_status=_http_for(why))

        # 2. confidence gate on flagged transitions
        if domain.requires_confidence_gate(state, event):
            from src.app.services.adaptive_action_gate import authorize
            gate = authorize(db, action_type=_GATE_ACTION.get(event, event), confidence=confidence,
                             subject=actor.id, target=case_id, tenant_id=tenant_id)
            if not gate.allowed:
                reason = f"gate:{gate.reason}"
                return TransitionResult(False, case_id, state.value, reason, http_status=403)

        # 3. apply — bitemporal version
        dst = domain.next_state(state, event, actor)
        if dst is None:  # defensive: can_fire passed but no dst (shouldn't happen)
            return TransitionResult(False, case_id, state.value, "illegal_transition", http_status=409)
        vid = repository.append_version(db, case_id=case_id, new_state=dst.value, event=event,
                                        reason_code=reason_code, actor_type=actor.type.value, actor_id=actor.id,
                                        evidence=evidence, state_patch=state_patch,
                                        idempotency_key=idempotency_key, tenant_id=tenant_id, now_iso=now_iso)
        if not vid:
            return TransitionResult(False, case_id, state.value, "persist_failed", http_status=409)

        # 4. commit state first, then emit the cross-session trace.
        # decision_log opens its own DB session; emitting while this write
        # transaction is still open can deadlock SQLite demo/test runs.
        try:
            db.commit()
        except Exception:
            return TransitionResult(False, case_id, dst.value, "commit_failed", http_status=409)
        _emit_trace(trace_id=trace_id or cur.source_trace_id, event=event, actor=actor, case_id=case_id,
                    evidence=evidence, reason_code=reason_code, valid_from=now_iso)
        if dst in FAILURE_STATES:
            # Step 10: route a terminal procurement failure into the governed exception queue so it reaches
            # a disposition instead of being a silent dead-end. enqueue_exception is non-raising (best-effort).
            from src.app.services.exception_resolver import enqueue_exception
            enqueue_exception(domain="procurement", terminal_outcome=dst.value.lower(), ref_id=case_id,
                              reason=reason_code, tenant_id=tenant_id, trace_id=trace_id or cur.source_trace_id)
        return TransitionResult(True, case_id, dst.value, "ok", version_id=vid)
    except Exception:
        return TransitionResult(False, case_id, None, "error", http_status=409)


def as_of(db, case_id: str, when: str, tenant_id: str = "default"):
    """Bitemporal read — the case version valid at business time ``when``."""
    return repository.version_asof(db, case_id, when, tenant_id)


def journey(db, case_id: str, tenant_id: str = "default"):
    return repository.journey(db, case_id, tenant_id)
