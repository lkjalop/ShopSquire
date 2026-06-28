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
from src.app.services.fulfillment import economics as feco
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


@router.get("/autonomous/audit")
def autonomous_audit(limit: int = Query(100, ge=1, le=1000),
                     role: str = Depends(require_role(_OPERATOR))) -> Dict[str, Any]:
    """WS-D observability: the autonomous-RFQ-send decision trail — what auto-sent (decision='allow') and
    every escalation with its reason (decision='escalate') — plus the LIVE toggle state so the operator can
    confirm autonomy is on/killed. This is the visibility that makes turning autonomy on responsible."""
    from src.app.services.adaptive_action_gate import load_recent_audit
    from src.app.services.fulfillment import autonomous_send as fauto
    from src.app.services.fulfillment.transport import transport_health
    with db_session() as db:
        rows = load_recent_audit(db, limit=limit, action_type="supplier_rfq_send")
    sent = sum(1 for r in rows if r["decision"] == "allow")
    escalated = sum(1 for r in rows if r["decision"] != "allow")
    by_reason: Dict[str, int] = {}
    for r in rows:
        if r["decision"] != "allow":
            by_reason[r["reason"] or "unknown"] = by_reason.get(r["reason"] or "unknown", 0) + 1
    return {"rows": rows, "summary": {"sent": sent, "escalated": escalated, "by_reason": by_reason},
            "enabled": fauto.is_enabled(), "killed": fauto.is_killed(), "transport": transport_health()}


@router.get("/cases/{case_id}")
def get_case(case_id: str, view: str = Query("operator")) -> Dict[str, Any]:
    with db_session() as db:
        return _case_view(db, case_id, for_operator=(view != "buyer"))


@router.get("/cases/by-trace/{trace_id}")
def get_case_by_trace(trace_id: str, view: str = Query("buyer")) -> Dict[str, Any]:
    """Resolve the procurement case opened from a decision trace_id — the link that lets the buyer's
    DecisionTrace surface the fulfilment journey for the same turn. 404 when no case was opened."""
    with db_session() as db:
        cid = fwf.repository.case_id_by_trace(db, trace_id)
        if not cid:
            raise HTTPException(status_code=404, detail="no case for trace")
        return {"trace_id": trace_id, **_case_view(db, cid, for_operator=(view != "buyer"))}


@router.get("/cases/{case_id}/journey")
def get_journey(case_id: str) -> Dict[str, Any]:
    with db_session() as db:
        return {"case_id": case_id, "journey": fwf.journey(db, case_id)}


@router.get("/cases/{case_id}/supplier-candidates")
def supplier_candidates(case_id: str, role: str = Depends(require_role(_OPERATOR))) -> Dict[str, Any]:
    """Ranked, confidence-scored, provenance-tagged APPROVED-supplier shortlist for the case's SKU — a
    read-only prefill so the operator can review + pick the recipient faster/safer before drafting. Contacts
    are resolved server-side from the allowlist/KYV (never buyer text); this never sends."""
    from src.app.services.fulfillment.supplier_contacts import supplier_contact_candidates
    with db_session() as db:
        cur = fwf.repository.current_version(db, case_id)
        if cur is None:
            raise HTTPException(status_code=404, detail="case not found")
        sj = cur.state_json if isinstance(cur.state_json, dict) else {}
        avail = sj.get("availability") if isinstance(sj.get("availability"), dict) else {}
        scope = (sj.get("draft") or {}).get("commercial_scope") if isinstance(sj.get("draft"), dict) else {}
        item_ref = str(avail.get("item_ref") or (scope or {}).get("item_ref") or "").strip()
        cands = supplier_contact_candidates(db, item_ref=item_ref) if item_ref else []
        return {"case_id": case_id, "item_ref": item_ref, "candidates": cands}


@router.get("/cases/{case_id}/rfq-fanout")
def rfq_fanout(case_id: str, top_n: int = Query(default=3, ge=1, le=8),
               role: str = Depends(require_role(_OPERATOR))) -> Dict[str, Any]:
    """Competitive RFQ preview: a FULLY-CAGED supplier draft for each of the top-N approved suppliers for
    the case's SKU (same claim-safety/evidence/gate as the single draft). Read-only preview — it never
    sends; the operator still approves each send through GATE 2. Recipients come from the allowlist."""
    from src.app.services.fulfillment.rfq_fanout import build_rfq_fanout, fanout_preview
    with db_session() as db:
        cur = fwf.repository.current_version(db, case_id)
        if cur is None:
            raise HTTPException(status_code=404, detail="case not found")
        sj = cur.state_json if isinstance(cur.state_json, dict) else {}
        avail = sj.get("availability") if isinstance(sj.get("availability"), dict) else {}
        scope = (sj.get("draft") or {}).get("commercial_scope") if isinstance(sj.get("draft"), dict) else {}
        item_ref = str(avail.get("item_ref") or (scope or {}).get("item_ref") or "").strip()
        qty = int((scope or {}).get("quantity") or avail.get("shortfall") or avail.get("requested_qty") or 0)
        if not item_ref:
            return {"case_id": case_id, "item_ref": "", "top_n": top_n, "quantity": qty, "drafts": []}
        drafts = build_rfq_fanout(db, item_ref=item_ref, quantity=qty, case_ref=case_id, top_n=int(top_n))
        return {"case_id": case_id, "item_ref": item_ref, "top_n": int(top_n), "quantity": qty,
                "count": len(drafts), "drafts": fanout_preview(drafts)}


class CompareQuotesBody(BaseModel):
    quotes: list[Dict[str, Any]] = []
    weights: Optional[Dict[str, float]] = None


@router.post("/cases/{case_id}/compare-quotes")
def compare_quotes_endpoint(case_id: str, body: CompareQuotesBody,
                            role: str = Depends(require_role(_OPERATOR))) -> Dict[str, Any]:
    """Rank competing supplier quotes by a vertical-blind composite (price · lead time · reliability) and
    recommend the best. Operator decision-support only; selecting + sending still go through the gates."""
    from src.app.services.fulfillment.rfq_fanout import compare_quotes
    with db_session() as db:
        if fwf.repository.current_version(db, case_id) is None:
            raise HTTPException(status_code=404, detail="case not found")
    result = compare_quotes(body.quotes or [], weights=body.weights)
    return {"case_id": case_id, **result}


@router.get("/cases/{case_id}/okf")
def case_okf(case_id: str, role: str = Depends(require_role(_OPERATOR))) -> Dict[str, Any]:
    """Export the case as an OKF (Open Knowledge Format) document — a portable, vendor-neutral
    "why-the-agent-decided-this" artifact (markdown + YAML frontmatter) any agent/auditor can read."""
    from src.app.services.fulfillment import okf_export
    with db_session() as db:
        cur = fwf.repository.current_version(db, case_id)
        if cur is None:
            raise HTTPException(status_code=404, detail="case not found")
        jr = fwf.journey(db, case_id)
        ts = str(jr[-1].get("valid_from")) if jr else ""
        md = okf_export.case_to_okf(case_id=case_id, state=cur.state, state_json=cur.state_json,
                                    journey=jr, timestamp=ts)
        return {"case_id": case_id, "type": "ProcurementCase",
                "filename": f"procurement-{case_id[:8]}.md", "okf": md}


@router.get("/cases/{case_id}/as-of")
def get_as_of(case_id: str, t: str = Query(...)) -> Dict[str, Any]:
    with db_session() as db:
        v = fwf.as_of(db, case_id, t)
        if v is None:
            raise HTTPException(status_code=404, detail="no version at that time")
        return {"case_id": case_id, "as_of": t, "state": v.state, "state_json": v.state_json}


@router.get("/cases/{case_id}/economics")
def get_economics(case_id: str, retail_unit_cents: Optional[int] = Query(None),
                  floor_margin_pct: float = Query(0.10),
                  role: str = Depends(require_role(_OPERATOR))) -> Dict[str, Any]:
    """OPERATOR-only deal economics: what the supplier charges us, our margin, how much discount we can
    hand the buyer while still clearing the floor, and the resulting profit. NEVER buyer-facing."""
    with db_session() as db:
        econ = feco.from_case(db, case_id, retail_unit_cents=retail_unit_cents,
                              floor_margin_pct=floor_margin_pct)
        return {"case_id": case_id, "economics": econ}


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


class EditDraftBody(BaseModel):
    subject: Optional[str] = None
    body: Optional[str] = None


@router.post("/cases/{case_id}/edit-draft")
def edit_draft(case_id: str, body: EditDraftBody, role: str = Depends(require_role(_OPERATOR))) -> Dict[str, Any]:
    """HUMAN edits the pending draft before approving — recomputes the hash (voids prior approval) and
    re-runs the claim-safety guard. Rejects an unsafe edit (price/commitment leak)."""
    human = Actor(ActorType.HUMAN_OPERATOR, role)
    with db_session() as db:
        res, _draft = fdraft.edit_draft(db, case_id=case_id, actor=human, subject=body.subject, body=body.body)
        _raise_if_failed(res)
        return _case_view(db, case_id, for_operator=True)


def _attempt_autonomous_send(db, case_id: str):
    """WS-C: once a case reaches AWAITING_APPROVAL, attempt a flag-gated autonomous RFQ send. SAFE-FIRST —
    any failing guard (or autonomy OFF, the default) leaves the case at AWAITING_APPROVAL for the human.
    Read the send parameters off the persisted draft; never raises into the endpoint."""
    from src.app.services.fulfillment import autonomous_send as fauto
    try:
        cur = fwf.repository.current_version(db, case_id)
        draft = (cur.state_json.get("draft") if cur else None) or {}
        scope = draft.get("commercial_scope") or {}
        return fauto.maybe_autonomous_send(
            db, case_id=case_id, actor=_agent(), confidence=float(draft.get("confidence") or 0.0),
            estimated_value_cents=int(scope.get("estimated_value_cents") or 0),
            quantity=int(scope.get("quantity") or 0), recipient_domain=str(draft.get("recipient_domain") or ""),
            allowlist_fn=fdraft._default_allowlist)
    except Exception:
        return fauto.SendDecision("escalated", "error_fail_closed")


@router.post("/cases/{case_id}/request-approval")
def request_approval(case_id: str, role: str = Depends(require_role(_OPERATOR))) -> Dict[str, Any]:
    with db_session() as db:
        res, approval_id = fdraft.request_supplier_approval(db, case_id=case_id, actor=_agent())
        _raise_if_failed(res)
        auto = _attempt_autonomous_send(db, case_id)
        return {**_case_view(db, case_id, for_operator=True), "approval_id": approval_id,
                "autonomous_send": {"action": auto.action, "reason": auto.reason,
                                    "provider_ref": auto.provider_ref}}


class RfiBody(BaseModel):
    question: str   # the scoped clarification the HUMAN wants to ask the supplier (claim-safe — no price)


@router.post("/cases/{case_id}/request-info")
def request_info(case_id: str, body: RfiBody, role: str = Depends(require_role(_OPERATOR))) -> Dict[str, Any]:
    """RFI: the HUMAN sends a scoped clarification to the resolved supplier before approving the RFQ — the
    recoverable path for a needs_info send-gate. Same cage (allowlisted recipient, claim-safe, hash-pinned)."""
    human = Actor(ActorType.HUMAN_OPERATOR, role)
    with db_session() as db:
        res, _rfi = fdraft.request_supplier_info(db, case_id=case_id, actor=human, question=body.question)
        _raise_if_failed(res)
        return _case_view(db, case_id, for_operator=True)


class RfiReplyBody(BaseModel):
    answer: str   # the supplier's clarification reply (returns the case to the approval gate)


@router.post("/cases/{case_id}/supplier-info")
def supplier_info(case_id: str, body: RfiReplyBody, role: str = Depends(require_role(_OPERATOR))) -> Dict[str, Any]:
    """Inbound RFI reply (AWAITING_SUPPLIER_INFO → AWAITING_APPROVAL). Fired as an EXTERNAL actor and
    trust-verified against the case's resolved supplier domain (an untrusted sender → 409), so the demo
    reply is attributed exactly as a real inbound poller would attribute it — not operator manual entry."""
    with db_session() as db:
        cur = fwf.repository.current_version(db, case_id)
        sender_domain = str(((cur.state_json.get("rfi") if cur else None) or {}).get("recipient_domain") or "")
        res = fec.receive_supplier_info(db, case_id=case_id, raw_body=body.answer, sender_domain=sender_domain)
        _raise_if_failed(res)
        return _case_view(db, case_id, for_operator=True)


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


# ── REAL market pipeline (operator) — live ingestion → analysis → findings, not synthetic replay ──
@router.post("/market/refresh")
def market_refresh(role: str = Depends(require_role(_OPERATOR))) -> Dict[str, Any]:
    """Run the REAL pipeline now (default tenant): backfill orders/conversion/search/returns → analyze →
    persist. Operator-triggered so the demo shows live findings without waiting for the beat schedule."""
    from src.app.services import market_pipeline as mp
    with db_session() as db:
        out = mp.run_pipeline(db, tenant_id="default")
        return {"refreshed": out, "state": mp.state(db)}


@router.get("/market/state")
def market_state(role: str = Depends(require_role(_OPERATOR))) -> Dict[str, Any]:
    """The REAL (default-tenant) findings — the live counterpart to /replay/state."""
    from src.app.services import market_pipeline as mp
    with db_session() as db:
        return mp.state(db)


# ── ranking-experiment console (operator) — promote/observe/evaluate/revert the live-adaptation loop ──
class ExperimentBody(BaseModel):
    experiment_id: Optional[str] = None
    min_samples: Optional[int] = None


def _exp_id(body: Optional["ExperimentBody"]) -> str:
    from src.app.services.experiment_console import DEFAULT_EXPERIMENT_ID
    return (body.experiment_id if body and body.experiment_id else DEFAULT_EXPERIMENT_ID)


@router.get("/market/experiment/state")
def experiment_state(experiment_id: Optional[str] = Query(None),
                     role: str = Depends(require_role(_OPERATOR))) -> Dict[str, Any]:
    from src.app.services import experiment_console as ec
    with db_session() as db:
        return ec.state(db, experiment_id=experiment_id or ec.DEFAULT_EXPERIMENT_ID)


@router.post("/market/experiment/promote")
def experiment_promote(body: ExperimentBody = Body(default=ExperimentBody()),
                       role: str = Depends(require_role(_OPERATOR))) -> Dict[str, Any]:
    """Arm the ranking experiment (status→live). The nudge still needs RANKING_NUDGE_EXPERIMENT_ENABLED."""
    from src.app.services import experiment_console as ec
    with db_session() as db:
        return ec.promote(db, experiment_id=_exp_id(body))


@router.post("/market/experiment/evaluate")
def experiment_evaluate(body: ExperimentBody = Body(default=ExperimentBody()),
                        role: str = Depends(require_role(_OPERATOR))) -> Dict[str, Any]:
    """Run uplift → decide → auto-revert now (the rollback safety net, on demand)."""
    from src.app.services import experiment_console as ec
    with db_session() as db:
        return ec.evaluate_now(db, experiment_id=_exp_id(body),
                               min_samples=int(body.min_samples) if body and body.min_samples else 30)


@router.post("/market/experiment/revert")
def experiment_revert(body: ExperimentBody = Body(default=ExperimentBody()),
                      role: str = Depends(require_role(_OPERATOR))) -> Dict[str, Any]:
    """The manual revert lever — stop the adaptation globally."""
    from src.app.services import experiment_console as ec
    with db_session() as db:
        return ec.revert(db, experiment_id=_exp_id(body))


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
