"""Fulfilment cases API — thin HTTP over the tested workflow. One bounded router (the doc: not separate
quote/mailbox/option routers). Each command maps to ONE workflow transition, so the domain guards +
bitemporal audit already hold; this layer only resolves the ACTOR (from role/uid) and translates the
TransitionResult to HTTP (404/403/409/200).

Role-scoped projection: an operator sees the full case; a buyer view is REDACTED (no draft body, no
wholesale price, no supplier identity). The demo-reply endpoint is DEMO-gated (default-OFF).
"""
from __future__ import annotations

import os
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel

from src.app.models.db import db_session
from src.app.security.auth import ROLE_MERCHANT, ROLE_OWNER, require_role
from src.app.services.fulfillment import draft as fdraft
from src.app.services.fulfillment import external_comms as fec
from src.app.services.fulfillment import options as fopt
from src.app.services.fulfillment import purchase_order as fpo
from src.app.services.fulfillment import sandbox_supplier as fsb
from src.app.services.fulfillment import workflow as fwf
from src.app.services.fulfillment.domain import Actor, ActorType

router = APIRouter(prefix="/api/v1/fulfillment", tags=["fulfillment"])

_OPERATOR = [ROLE_MERCHANT, ROLE_OWNER]


def _demo_enabled() -> bool:
    return str(os.getenv("FULFILLMENT_DEMO_ENABLED", "0")).strip().lower() in ("1", "true", "yes", "on")


def _agent() -> Actor:
    return Actor(ActorType.AGENT, "Procurement_Agent")


def _raise_if_failed(res: "fwf.TransitionResult") -> None:
    if not res.ok:
        raise HTTPException(status_code=res.http_status, detail=res.reason)


# buyer never sees these supplier-private fields
_BUYER_REDACT = ("draft", "inbound", "quarantine")


def _case_view(db, case_id: str, *, for_operator: bool) -> Dict[str, Any]:
    cur = fwf.repository.current_version(db, case_id)
    if cur is None:
        raise HTTPException(status_code=404, detail="case not found")
    state_json = dict(cur.state_json)
    if not for_operator:
        for k in _BUYER_REDACT:
            state_json.pop(k, None)
        vq = state_json.get("validated_quote")
        if isinstance(vq, dict):  # strip wholesale unit cost from the buyer projection
            state_json["validated_quote"] = {k: v for k, v in vq.items()
                                             if k not in ("unit_amount_cents", "evidence_spans")}
        po = state_json.get("purchase_order")
        if isinstance(po, dict):  # buyer sees the confirmation (ref/status/qty), not wholesale or supplier
            state_json["purchase_order"] = {k: v for k, v in po.items()
                                            if k not in ("unit_amount_cents", "total_amount_cents", "supplier_ref")}
    return {"case_id": case_id, "state": cur.state, "state_json": state_json,
            "source_trace_id": cur.source_trace_id}


# ── reads ─────────────────────────────────────────────────────────────────────
@router.get("/cases")
def list_cases(role: str = Depends(require_role(_OPERATOR))) -> Dict[str, Any]:
    with db_session() as db:
        return {"cases": fwf.repository.list_cases(db)}


@router.get("/cases/{case_id}")
def get_case(case_id: str, view: str = Query("operator")) -> Dict[str, Any]:
    with db_session() as db:
        return _case_view(db, case_id, for_operator=(view != "buyer"))


@router.get("/cases/{case_id}/journey")
def get_journey(case_id: str) -> Dict[str, Any]:
    with db_session() as db:
        return {"case_id": case_id, "journey": fwf.journey(db, case_id)}


@router.get("/cases/{case_id}/as-of")
def get_as_of(case_id: str, t: str = Query(...)) -> Dict[str, Any]:
    with db_session() as db:
        v = fwf.as_of(db, case_id, t)
        if v is None:
            raise HTTPException(status_code=404, detail="no version at that time")
        return {"case_id": case_id, "as_of": t, "state": v.state, "state_json": v.state_json}


# ── commands ──────────────────────────────────────────────────────────────────
class OpenBody(BaseModel):
    uid: Optional[str] = None
    trace_id: Optional[str] = None


@router.post("/cases")
def open_case(body: OpenBody = Body(default=OpenBody()), role: str = Depends(require_role(_OPERATOR))) -> Dict[str, Any]:
    with db_session() as db:
        cid = fwf.open_case(db, buyer_uid_hash=body.uid, source_trace_id=body.trace_id, requested_by=role)
        db.commit()
        if not cid:
            raise HTTPException(status_code=500, detail="could not open case")
        return {"case_id": cid, "state": "NEW"}


class AssessBody(BaseModel):
    requested_qty: int
    in_stock: int = 0
    item_ref: str = ""


@router.post("/cases/{case_id}/assess")
def assess(case_id: str, body: AssessBody, role: str = Depends(require_role(_OPERATOR))) -> Dict[str, Any]:
    """Agent records availability + asks the buyer to commit (the case waits at GATE 1)."""
    with db_session() as db:
        avail = {"requested_qty": body.requested_qty, "in_stock": body.in_stock,
                 "shortfall": max(0, body.requested_qty - body.in_stock), "item_ref": body.item_ref}
        _raise_if_failed(fwf.transition(db, case_id=case_id, event="availability_assessed", actor=_agent(),
                                        state_patch={"availability": avail}, reason_code="inventory_truth"))
        res = fwf.transition(db, case_id=case_id, event="request_buyer_commitment", actor=_agent())
        _raise_if_failed(res)
        return _case_view(db, case_id, for_operator=True)


class CommitBody(BaseModel):
    uid: str


@router.post("/cases/{case_id}/commit")
def commit(case_id: str, body: CommitBody) -> Dict[str, Any]:
    """GATE 1: the BUYER commits (places the order / requests sourcing). No operator role required —
    this is the buyer's own action; only now may a supplier be engaged."""
    with db_session() as db:
        res = fwf.transition(db, case_id=case_id, event="buyer_committed", actor=Actor(ActorType.BUYER, body.uid),
                             reason_code="buyer_commitment")
        _raise_if_failed(res)
        return _case_view(db, case_id, for_operator=False)


class DraftBody(BaseModel):
    item_ref: str
    quantity: int
    estimated_value_cents: int = 0


@router.post("/cases/{case_id}/draft-quote")
def draft_quote(case_id: str, body: DraftBody, role: str = Depends(require_role(_OPERATOR))) -> Dict[str, Any]:
    with db_session() as db:
        res, draft = fdraft.draft_and_record(db, case_id=case_id, actor=_agent(), item_ref=body.item_ref,
                                             quantity=body.quantity, estimated_value_cents=body.estimated_value_cents)
        _raise_if_failed(res)
        return _case_view(db, case_id, for_operator=True)


@router.post("/cases/{case_id}/request-approval")
def request_approval(case_id: str, role: str = Depends(require_role(_OPERATOR))) -> Dict[str, Any]:
    with db_session() as db:
        res, approval_id = fdraft.request_supplier_approval(db, case_id=case_id, actor=_agent())
        _raise_if_failed(res)
        return {**_case_view(db, case_id, for_operator=True), "approval_id": approval_id}


class DispatchBody(BaseModel):
    content_hash: str   # the hash of the message the human APPROVED (an edit since then → stale_approval)


@router.post("/cases/{case_id}/dispatch")
def dispatch(case_id: str, body: DispatchBody, role: str = Depends(require_role(_OPERATOR))) -> Dict[str, Any]:
    """GATE 2: the HUMAN approves + sends. approval_granted then the hash-checked send."""
    human = Actor(ActorType.HUMAN_OPERATOR, role)
    with db_session() as db:
        _raise_if_failed(fwf.transition(db, case_id=case_id, event="approval_granted", actor=human,
                                        reason_code="human_approved"))
        res = fec.send_approved(db, case_id=case_id, actor=human, approval_content_hash=body.content_hash)
        _raise_if_failed(res)
        return _case_view(db, case_id, for_operator=True)


class DemoReplyBody(BaseModel):
    scenario: str = "full_quote"
    requested_qty: int = 6


@router.post("/cases/{case_id}/demo-reply")
def demo_reply(case_id: str, body: DemoReplyBody, role: str = Depends(require_role(_OPERATOR))) -> Dict[str, Any]:
    """DEMO-only (FULFILLMENT_DEMO_ENABLED): inject a deterministic supplier reply, correlate, parse."""
    if not _demo_enabled():
        raise HTTPException(status_code=403, detail="demo replies disabled")
    if body.scenario not in fsb.SCENARIOS:
        raise HTTPException(status_code=400, detail=f"unknown scenario; choose from {sorted(fsb.SCENARIOS)}")
    with db_session() as db:
        reply = fsb.generate_reply(case_ref=case_id, scenario=body.scenario, requested_qty=body.requested_qty)
        res = fec.receive_reply(db, case_id=case_id, raw_body=reply["body"], sender_domain=reply["sender_domain"],
                                provider_ref=reply["provider_ref"])
        _raise_if_failed(res)
        if res.state == "QUOTE_RECEIVED":
            fec.record_parsed(db, case_id=case_id, actor=_agent())
        return _case_view(db, case_id, for_operator=True)


@router.post("/cases/{case_id}/validate-quote")
def validate_quote(case_id: str, role: str = Depends(require_role(_OPERATOR))) -> Dict[str, Any]:
    with db_session() as db:
        res = fec.validate_quote(db, case_id=case_id, actor=Actor(ActorType.HUMAN_OPERATOR, role))
        _raise_if_failed(res)
        return _case_view(db, case_id, for_operator=True)


class OptionsBody(BaseModel):
    deadline: Optional[str] = None
    local_delivery_at: Optional[str] = None
    substitute: Optional[Dict[str, Any]] = None


@router.post("/cases/{case_id}/options")
def generate_options(case_id: str, body: OptionsBody = Body(default=OptionsBody()),
                     role: str = Depends(require_role(_OPERATOR))) -> Dict[str, Any]:
    with db_session() as db:
        res, _opts = fopt.generate_and_record(db, case_id=case_id, actor=_agent(), deadline=body.deadline,
                                              local_delivery_at=body.local_delivery_at, substitute=body.substitute)
        _raise_if_failed(res)
        return _case_view(db, case_id, for_operator=False)  # buyer-facing


# ── market replay (DEMO-only, operator) ──────────────────────────────────────
@router.post("/replay/reset")
def replay_reset(role: str = Depends(require_role(_OPERATOR))) -> Dict[str, Any]:
    if not _demo_enabled():
        raise HTTPException(status_code=403, detail="replay disabled")
    from src.app.services import market_replay as mr
    with db_session() as db:
        return {"reset": mr.reset(db)}


@router.post("/replay/advance")
def replay_advance(day: int = Query(...), role: str = Depends(require_role(_OPERATOR))) -> Dict[str, Any]:
    if not _demo_enabled():
        raise HTTPException(status_code=403, detail="replay disabled")
    from src.app.services import market_replay as mr
    with db_session() as db:
        loaded = mr.load_days(db, up_to_day=day)
        ran = mr.run(db)
        return {"loaded": loaded, "analysis": ran, "state": mr.state(db)}


@router.get("/replay/state")
def replay_state(role: str = Depends(require_role(_OPERATOR))) -> Dict[str, Any]:
    from src.app.services import market_replay as mr
    with db_session() as db:
        return mr.state(db)


class SelectBody(BaseModel):
    uid: str
    option_id: str


@router.post("/cases/{case_id}/select-option")
def select_option(case_id: str, body: SelectBody) -> Dict[str, Any]:
    """BUYER picks an offered option (no operator role — the buyer's own action)."""
    with db_session() as db:
        res = fopt.select_option(db, case_id=case_id, actor=Actor(ActorType.BUYER, body.uid), option_id=body.option_id)
        _raise_if_failed(res)
        return _case_view(db, case_id, for_operator=False)


# ── PO finalization: AGENT proposes, HUMAN approves+creates, then completes ─────
@router.post("/cases/{case_id}/propose-po")
def propose_po(case_id: str, role: str = Depends(require_role(_OPERATOR))) -> Dict[str, Any]:
    """AGENT drafts the PO from the buyer's selection (SELECTED → PROCUREMENT_APPROVAL_REQUIRED).
    No value is committed — this only stages the PO for the human's approval."""
    with db_session() as db:
        _raise_if_failed(fpo.propose(db, case_id=case_id, actor=_agent()))
        return _case_view(db, case_id, for_operator=True)


class ExecutePOBody(BaseModel):
    idempotency_key: Optional[str] = None  # a double-clicked execute creates exactly one PO
    today: Optional[str] = None            # for as-of/expiry checks; defaults to server date


@router.post("/cases/{case_id}/execute-po")
def execute_po(case_id: str, body: ExecutePOBody = Body(default=ExecutePOBody()),
               role: str = Depends(require_role(_OPERATOR))) -> Dict[str, Any]:
    """HUMAN approves AND creates the PO (APPROVAL_REQUIRED → IN_PROGRESS → READY_TO_SHIP). Refused if
    the quote expired or the PO exceeds the approved scope. SANDBOX: records a PO ref, transmits nothing."""
    human = Actor(ActorType.HUMAN_OPERATOR, role)
    with db_session() as db:
        res = fpo.execute(db, case_id=case_id, actor=human, idempotency_key=body.idempotency_key,
                          today=body.today)
        _raise_if_failed(res)
        return _case_view(db, case_id, for_operator=True)


@router.post("/cases/{case_id}/complete")
def complete_case(case_id: str, role: str = Depends(require_role(_OPERATOR))) -> Dict[str, Any]:
    """HUMAN marks the order COMPLETED (READY_TO_SHIP → COMPLETED) — the journey's final act."""
    with db_session() as db:
        res = fpo.complete(db, case_id=case_id, actor=Actor(ActorType.HUMAN_OPERATOR, role))
        _raise_if_failed(res)
        return _case_view(db, case_id, for_operator=True)
