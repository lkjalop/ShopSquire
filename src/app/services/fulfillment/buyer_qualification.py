"""Buyer qualification (agnostic CORE) — Phase 3.

Before any supplier is contacted for a bulk request, a HUMAN confirms the buyer is actually serious (right
quantity, real deadline, genuine intent). This records that verdict on the case bitemporally and gates the
draft: with FULFILLMENT_REQUIRE_QUALIFICATION on, no RFQ may be drafted until the case is qualified.

The conversation itself happens in the escalation room (buyer ↔ staff) — the router opens it via
create_incident_record and passes the resulting room reference here. This module owns only the
state-machine + gate; it never sends to a supplier. Vertical-blind; never raises into a caller.
"""
from __future__ import annotations

import os
from typing import Any, Dict, Optional

from src.app.services.fulfillment import workflow
from src.app.services.fulfillment.domain import Actor


def qualification_required(flags: Optional[Dict[str, Any]] = None) -> bool:
    """Whether a draft must wait for a human qualification verdict. Default OFF (env or feature flag)."""
    raw = os.getenv("FULFILLMENT_REQUIRE_QUALIFICATION")
    if raw is not None:
        return str(raw).strip().lower() in ("1", "true", "yes", "on")
    v = (flags or {}).get("FULFILLMENT_REQUIRE_QUALIFICATION") if isinstance(flags, dict) else None
    return str(v).strip().lower() in ("1", "true", "yes", "on") if v is not None else False


def qualification_status(case_state: Optional[Dict[str, Any]]) -> Optional[str]:
    q = (case_state or {}).get("qualification") if isinstance(case_state, dict) else None
    return str(q.get("status")) if isinstance(q, dict) and q.get("status") else None


def is_qualified(case_state: Optional[Dict[str, Any]]) -> bool:
    return qualification_status(case_state) == "qualified"


def request_qualification(db, *, case_id: str, actor: Actor, room_ref: Optional[str] = None,
                          tenant_id: str = "default", now_iso: Optional[str] = None,
                          trace_id: Optional[str] = None) -> workflow.TransitionResult:
    """Mark the case as awaiting a human qualification (a buyer-clarification room was opened). room_ref is
    the escalation incident id the operator/buyer converse in. Records status='requested' on the case."""
    return workflow.transition(
        db, case_id=case_id, event="buyer_qualification_requested", actor=actor,
        reason_code="qualify_buyer_intent",
        evidence={"room_ref": room_ref, "requested_by": getattr(actor, "id", None)},
        state_patch={"qualification": {"status": "requested", "room_ref": room_ref,
                                       "requested_by": getattr(actor, "id", None)}},
        tenant_id=tenant_id, now_iso=now_iso, trace_id=trace_id)


def record_qualification(db, *, case_id: str, actor: Actor, qualified: bool, notes: Optional[str] = None,
                         room_ref: Optional[str] = None, tenant_id: str = "default",
                         now_iso: Optional[str] = None, trace_id: Optional[str] = None) -> workflow.TransitionResult:
    """HUMAN records the verdict after talking to the buyer. qualified → supplier contact is now permitted;
    not qualified → the case ends (BUYER_DECLINED), no supplier is ever contacted. Bitemporally recorded."""
    if qualified:
        return workflow.transition(
            db, case_id=case_id, event="buyer_qualified", actor=actor, reason_code="buyer_verified_serious",
            evidence={"verified_by": getattr(actor, "id", None), "notes": notes, "room_ref": room_ref},
            state_patch={"qualification": {"status": "qualified", "verified_by": getattr(actor, "id", None),
                                           "notes": notes, "room_ref": room_ref}},
            tenant_id=tenant_id, now_iso=now_iso, trace_id=trace_id)
    return workflow.transition(
        db, case_id=case_id, event="buyer_disqualified", actor=actor, reason_code="buyer_not_serious",
        evidence={"verified_by": getattr(actor, "id", None), "notes": notes, "room_ref": room_ref},
        state_patch={"qualification": {"status": "disqualified", "verified_by": getattr(actor, "id", None),
                                       "notes": notes, "room_ref": room_ref}},
        tenant_id=tenant_id, now_iso=now_iso, trace_id=trace_id)
