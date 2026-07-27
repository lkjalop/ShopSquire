"""Fulfilment cases API — thin HTTP over the tested workflow. One bounded router (the doc: not separate
quote/mailbox/option routers). Each command maps to ONE workflow transition, so the domain guards +
bitemporal audit already hold; this layer only resolves the ACTOR (from role/uid) and translates the
TransitionResult to HTTP (404/403/409/200).

Role-scoped projection: an operator sees the full case; a buyer view is REDACTED (no draft body, no
wholesale price, no supplier identity). The demo-reply endpoint is DEMO-gated (default-OFF).
"""
from __future__ import annotations
from src.app.feature_flags import get_flags as _ff_get_flags

import os
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from src.app.models.db import db_session
from src.app.security.auth import ROLE_MERCHANT, ROLE_OWNER, OperatorSubject, operator_subject, require_role


def _operator_actor(role: str, subj: "OperatorSubject") -> Actor:
    """A HUMAN_OPERATOR actor stamped with the per-user identity when a JWT carried one, else a 'key:<role>'
    sentinel so the audit shows 'shared key, no user'. role stays the AUTHORITY axis; user_id the AUDIT axis."""
    uid = (getattr(subj, "user_id", "") or "").strip() or f"key:{role}"
    return Actor(ActorType.HUMAN_OPERATOR, role, user_id=uid)
from src.app.services.fulfillment import draft as fdraft
from src.app.services.fulfillment import economics as feco
from src.app.services.fulfillment import external_comms as fec
from src.app.services.fulfillment import options as fopt
from src.app.services.fulfillment import order_split as fos
from src.app.services.fulfillment import purchase_order as fpo
from src.app.services.fulfillment import sandbox_supplier as fsb
from src.app.services.fulfillment import workflow as fwf
from src.app.services.fulfillment.domain import Actor, ActorType

router = APIRouter(prefix="/api/v1/fulfillment", tags=["fulfillment"])

_OPERATOR = [ROLE_MERCHANT, ROLE_OWNER]

# Anti-abuse: cap cart-confirmations per buyer per minute. Rapid confirm/amend churn is a
# resource-exhaustion vector (each cycle resolves SKUs, plans routing, materializes/supersedes cases), so
# this is a cost AND a security control. Default 20/min; 0 disables. Reuses the shared fixed-window limiter.
_CONFIRM_RATE_PER_MIN = int(os.getenv("FULFILLMENT_CONFIRM_RATE_PER_MIN", "20") or 20)


def _demo_enabled() -> bool:
    return str(os.getenv("FULFILLMENT_DEMO_ENABLED", "0")).strip().lower() in ("1", "true", "yes", "on")


def _truthy(v: Any) -> bool:
    return str(v).strip().lower() in ("1", "true", "yes", "on")


def _auto_draft_on_commit_enabled() -> bool:
    """Internal-only RFQ draft after GATE 1. Does not send; GATE 2 remains human/autonomy-governed."""
    raw = os.getenv("FULFILLMENT_AUTO_DRAFT_ON_COMMIT")
    if raw is not None:
        return _truthy(raw)
    try:
        from src.app.config import get_settings, load_feature_flags
        flags = _ff_get_flags() or {}
        return _truthy(flags.get("FULFILLMENT_AUTO_DRAFT_ON_COMMIT"))
    except Exception:
        return False


def _agent() -> Actor:
    return Actor(ActorType.AGENT, "Procurement_Agent")


def _raise_if_failed(res: "fwf.TransitionResult") -> None:
    if not res.ok:
        raise HTTPException(status_code=res.http_status, detail=res.reason)


# buyer never sees these supplier-private fields
_BUYER_REDACT = ("draft", "inbound", "quarantine")


def _buyer_procurement_trace(draft: Any) -> Optional[Dict[str, Any]]:
    """Expose workflow proof without leaking supplier-private message content or economics."""
    if not isinstance(draft, dict):
        return None
    scope = draft.get("commercial_scope") if isinstance(draft.get("commercial_scope"), dict) else {}
    channel = draft.get("channel_plan") if isinstance(draft.get("channel_plan"), dict) else {}
    gate = draft.get("send_gate") or draft.get("gate")
    gate = gate if isinstance(gate, dict) else {}
    reasons = gate.get("blocking") or gate.get("reasons") or []
    if not isinstance(reasons, list):
        reasons = [reasons]
    return {
        "drafted": True,
        "status": "human_gated_not_sent",
        "item_ref": scope.get("item_ref"),
        "quantity": scope.get("quantity"),
        "currency": scope.get("currency"),
        "channel": channel.get("channel"),
        "requires_human": bool(channel.get("requires_human")),
        "integration_kind": channel.get("integration_kind"),
        "gate_decision": gate.get("decision"),
        "gate_reasons": [str(reason) for reason in reasons if reason],
        "content_hash": draft.get("content_hash"),
    }


def _case_view(db, case_id: str, *, for_operator: bool) -> Dict[str, Any]:
    cur = fwf.repository.current_version(db, case_id)
    if cur is None:
        raise HTTPException(status_code=404, detail="case not found")
    state_json = dict(cur.state_json)
    if not for_operator:
        procurement_trace = _buyer_procurement_trace(state_json.get("draft"))
        if procurement_trace:
            state_json["procurement_trace"] = procurement_trace
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
    # bounded-autonomy buyer status reply (claim-safe, no commitment) — surfaced so the buyer always
    # knows where their bulk request stands as it progresses. Safe to show without human approval.
    from src.app.services.fulfillment.buyer_reply import buyer_status_message
    out: Dict[str, Any] = {"case_id": case_id, "state": cur.state, "state_json": state_json,
                           "source_trace_id": cur.source_trace_id}
    msg = buyer_status_message(cur.state, cur.state_json)
    if msg:
        out["buyer_status"] = msg
    if for_operator:
        quarantine = state_json.get("quarantine")
        inbox_id = str((quarantine or {}).get("inbox_id") or "") if isinstance(quarantine, dict) else ""
        if inbox_id:
            try:
                rows = db.execute(
                    __import__("sqlalchemy").text(
                        "SELECT action, actor_id, note, fresh_case_id, created_at "
                        "FROM inbound_email_quarantine_disposition "
                        "WHERE inbox_id=:inbox ORDER BY created_at ASC"
                    ),
                    {"inbox": inbox_id},
                ).fetchall()
                out["quarantine_dispositions"] = [
                    {
                        "action": row[0], "actor_id": row[1], "note": row[2],
                        "fresh_case_id": row[3], "created_at": row[4],
                    }
                    for row in rows
                ]
                job = db.execute(
                    __import__("sqlalchemy").text(
                        "SELECT enrichment_status, enrichment_attempts, enrichment_error "
                        "FROM inbound_email_inbox WHERE id=:inbox"
                    ),
                    {"inbox": inbox_id},
                ).fetchone()
                if job:
                    out["email_enrichment"] = {
                        "status": job[0], "attempts": job[1], "error": job[2],
                    }
            except Exception:
                pass
    try:
        from src.app.services.fulfillment.draft_retry import status_for_case
        retry = status_for_case(db, case_id)
        if retry and retry.get("status") != "succeeded":
            out["draft_status"] = retry
    except Exception:
        pass
    # SELL ENGINE (operator, rung A): at the send-decision states, surface margin + discount headroom so the
    # operator decides whether the reorder is worth it BEFORE approving the supplier send. Pure analysis;
    # never blocks the transition (warn-by-default) — the human still commits (GATE 2). Best-effort.
    if for_operator and cur.state in _SEND_DECISION_STATES:
        try:
            from src.app.services.fulfillment.margin_advisor import assess as _margin_assess
            adv = _margin_assess(db, case_id)
            if adv.get("available"):
                out["margin_advice"] = _attach_sales_response(db, case_id, adv)  # M4→M5 demand-aware overlay
                if adv.get("verdict") == "below_floor" and _margin_gate_mode() != "off":
                    out["margin_warning"] = {
                        "mode": _margin_gate_mode(),
                        "message": "List margin is below the floor — confirm this reorder is worth it before sending.",
                    }
        except Exception:
            pass
    return out


# states at which the operator is deciding whether to send the supplier reorder — surface margin here.
_SEND_DECISION_STATES = frozenset({"QUOTE_DRAFTED", "AWAITING_APPROVAL", "APPROVED_TO_SEND"})


def _margin_gate_mode() -> str:
    """Governable margin gate: 'warn' (default, informational), 'off' (suppress), or 'block' (the admin UI
    requires an explicit override). Server never hard-blocks the human's send — informing is the control."""
    return str(os.getenv("FULFILLMENT_MARGIN_GATE", "warn")).strip().lower() or "warn"


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
def get_case(case_id: str, request: Request) -> Dict[str, Any]:
    from src.app.security.buyer_principal import assert_case_owner, resolve_buyer_principal
    principal = resolve_buyer_principal(request)
    with db_session() as db:
        assert_case_owner(db, case_id, principal)
        return _case_view(db, case_id, for_operator=False)


@router.get("/cases/{case_id}/operator-view")
def get_case_operator(case_id: str, role: str = Depends(require_role(_OPERATOR))) -> Dict[str, Any]:
    with db_session() as db:
        return _case_view(db, case_id, for_operator=True)


@router.get("/cases/by-trace/{trace_id}")
def get_case_by_trace(trace_id: str, request: Request) -> Dict[str, Any]:
    """Resolve the procurement case opened from a decision trace_id — the link that lets the buyer's
    DecisionTrace surface the fulfilment journey for the same turn. 404 when no case was opened."""
    from src.app.security.buyer_principal import assert_case_owner, resolve_buyer_principal
    principal = resolve_buyer_principal(request)
    with db_session() as db:
        cid = fwf.repository.case_id_by_trace(db, trace_id)
        if not cid:
            raise HTTPException(status_code=404, detail="no case for trace")
        assert_case_owner(db, cid, principal)
        return {"trace_id": trace_id, **_case_view(db, cid, for_operator=False)}


@router.get("/cases/by-trace/{trace_id}/operator-view")
def get_case_by_trace_operator(trace_id: str,
                               role: str = Depends(require_role(_OPERATOR))) -> Dict[str, Any]:
    with db_session() as db:
        cid = fwf.repository.case_id_by_trace(db, trace_id)
        if not cid:
            raise HTTPException(status_code=404, detail="no case for trace")
        return {"trace_id": trace_id, **_case_view(db, cid, for_operator=True)}


def _cases_by_trace_view(
    trace_id: str,
    *,
    for_operator: bool,
    principal: Any = None,
) -> Dict[str, Any]:
    """READ-ONLY: every ACTIVE case opened from a decision trace — a multi-supplier bulk order opens one
    case per supplier group, all sharing the trace, so the Decision Trace → Procurement tab can show ALL
    the drafted RFQs (one per supplier), not just the newest. Superseded cases are excluded (they belong to
    a prior amendment). Proof surface only; it never mutates or sends. Empty list (not 404) when none."""
    with db_session() as db:
        cids = fwf.repository.case_ids_by_trace(db, trace_id)
        cases: List[Dict[str, Any]] = []
        order_group_id: Optional[str] = None
        for cid in cids:
            try:
                if not for_operator:
                    from src.app.security.buyer_principal import assert_case_owner
                    assert_case_owner(db, cid, principal)
                cv = _case_view(db, cid, for_operator=for_operator)
            except HTTPException:
                continue
            if str(cv.get("state") or "").upper() == "SUPERSEDED":
                continue  # a prior amendment's retired case — not part of the current order
            order_group_id = order_group_id or (cv.get("state_json") or {}).get("order_group_id")
            cases.append(cv)
        return {"trace_id": trace_id, "order_group_id": order_group_id,
                "case_count": len(cases), "cases": cases}


@router.get("/cases/by-trace/{trace_id}/all")
def get_cases_by_trace_all(trace_id: str, request: Request) -> Dict[str, Any]:
    from src.app.security.buyer_principal import resolve_buyer_principal
    return _cases_by_trace_view(
        trace_id,
        for_operator=False,
        principal=resolve_buyer_principal(request),
    )


@router.get("/cases/by-trace/{trace_id}/all/operator-view")
def get_cases_by_trace_all_operator(trace_id: str,
                                    role: str = Depends(require_role(_OPERATOR))) -> Dict[str, Any]:
    return _cases_by_trace_view(trace_id, for_operator=True)


@router.get("/cases/{case_id}/journey")
def get_journey(case_id: str, request: Request) -> Dict[str, Any]:
    from src.app.security.buyer_principal import assert_case_owner, resolve_buyer_principal
    principal = resolve_buyer_principal(request)
    with db_session() as db:
        assert_case_owner(db, case_id, principal)
        return {"case_id": case_id, "journey": fwf.journey(db, case_id)}


@router.get("/cases/by-order/{order_id}")
def cases_by_order(order_id: str, role: str = Depends(require_role(_OPERATOR))) -> Dict[str, Any]:
    """The amendment history of one order (#5): every case under the order group — active + superseded,
    newest-first — plus a draft-DIFF showing what changed between the most-recently-superseded draft and the
    current active draft. Lets the operator see 'what the buyer changed' across an amendment."""
    from src.app.services.fulfillment.cart_commitment import draft_diff, list_order_cases
    with db_session() as db:
        cases = list_order_cases(db, order_id, include_body=True)
        active = next((c for c in cases if not c["superseded"]), None)
        prior = next((c for c in cases if c["superseded"]), None)
        diff = draft_diff(prior["draft"], active["draft"]) if (active and prior) else None
        return {"order_id": order_id, "case_count": len(cases), "cases": cases, "draft_diff": diff}


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


def _attach_sales_response(db, case_id: str, advice: Dict[str, Any]) -> Dict[str, Any]:
    """M4→M5 demand-aware overlay on the margin advice: given demand trend + stock position, HOW to use the
    discount headroom (increase to clear surplus / reduce to protect a rising line). Recommends, never
    applies; the recommended discount is margin-clamped by the policy. Best-effort — never breaks the
    margin verdict (returns ``advice`` unchanged on any failure)."""
    if not advice.get("available"):
        return advice
    try:
        from src.app.services.sales_response_policy import assess_sales_response
        from src.app.services.market_analysis import load_recent_findings
        cur = fwf.repository.current_version(db, case_id)
        avail = (cur.state_json.get("availability") if cur and isinstance(cur.state_json, dict) else {}) or {}
        sr = assess_sales_response(demand_findings=load_recent_findings(db, limit=50),
                                   availability=avail, economics=advice.get("economics"))
        advice["sales_response"] = sr.as_dict()
    except Exception as _srx:
        import logging
        logging.getLogger("shopsquire.fulfillment").debug("sales_response overlay skipped: %s", _srx)
    return advice


@router.get("/cases/{case_id}/margin-advice")
def get_margin_advice(case_id: str, retail_unit_cents: Optional[int] = Query(None),
                      floor_margin_pct: float = Query(0.10),
                      role: str = Depends(require_role(_OPERATOR))) -> Dict[str, Any]:
    """OPERATOR-only sell-engine advice (rung A): the margin verdict (healthy/thin/below_floor), the discount
    we could offer the buyer to close while keeping a buffer above the floor, the hard discount ceiling, and
    the historical supplier price. Pure analysis — proposing, never committing. Read it BEFORE approving the
    supplier send to judge whether the reorder is worth it."""
    from src.app.services.fulfillment.margin_advisor import assess as _margin_assess
    with db_session() as db:
        advice = _margin_assess(db, case_id, retail_unit_cents=retail_unit_cents, floor_margin_pct=floor_margin_pct)
        return {"case_id": case_id, **_attach_sales_response(db, case_id, advice)}


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


class SplitLineBody(BaseModel):
    item_ref: str
    requested_qty: int
    in_stock: int = 0
    source_qty: Optional[int] = None
    shortfall: Optional[int] = None
    line_id: Optional[str] = None


class SplitPlanBody(BaseModel):
    lines: list[SplitLineBody]
    trace_id: Optional[str] = None


@router.post("/split-plan")
def split_plan(body: SplitPlanBody, role: str = Depends(require_role(_OPERATOR))) -> Dict[str, Any]:
    """Plan a mixed buyer request into supplier-resolved sourcing groups.

    Read-only: no supplier contact, no PO, no case creation. This is the safe bridge for requests such as
    "15 laptops plus monitors/headsets" while the core RFQ case remains one commercial scope per case.
    """
    with db_session() as db:
        plan = fos.plan_order_split(
            db,
            lines=[x.model_dump() for x in (body.lines or [])],
        )
        fos.emit_split_trace(body.trace_id, plan=plan)
        return plan


class FromOrderBody(BaseModel):
    query: Optional[str] = None                       # "15 laptops + 10 monitors + 5 headsets" (parsed)
    lines: Optional[list[SplitLineBody]] = None       # OR explicit resolved lines
    uid: Optional[str] = None
    trace_id: Optional[str] = None


@router.post("/cases/from-order")
def cases_from_order(body: FromOrderBody, role: str = Depends(require_role(_OPERATOR))) -> Dict[str, Any]:
    """Multi-line order → REAL cases: parse/resolve the buyer's mixed request into lines, plan the supplier
    split, then create ONE procurement case per supplier group (each case at GATE 1 — no supplier contacted).
    Accepts an explicit `lines` list or a raw `query` to parse. Returns the plan + the created cases."""
    with db_session() as db:
        if body.lines:
            lines = fos.resolve_line_skus(db, [x.model_dump() for x in body.lines])
        else:
            lines = fos.resolve_line_skus(db, fos.parse_order_lines(body.query or ""))
        if not lines:
            raise HTTPException(status_code=422, detail="no_order_lines_resolved")
        plan = fos.plan_order_split(db, lines=lines)
        fos.emit_split_trace(body.trace_id, plan=plan)
        created = fos.create_grouped_cases(db, plan=plan, uid=body.uid, trace_id=body.trace_id)
        return {"plan": plan, **created}


class ConfirmCartBody(BaseModel):
    uid: Optional[str] = None
    order_id: str                                 # commitment reference (cart/order id) — the idempotency key
    lines: Optional[list[SplitLineBody]] = None   # explicit resolved lines, OR
    query: Optional[str] = None                   # a raw mixed message to parse ("15 laptops + 10 monitors")
    trace_id: Optional[str] = None
    supersede: bool = False                        # buyer amending a confirmed order → retire old cases + re-source
    requirements: Optional[Dict[str, Any]] = None  # buyer deadline/use_case/ship_to (from the preview) → onto the case


def _client_network(request: Optional[Request]) -> Dict[str, Any]:
    """Best-effort {bot_suspect, geo_risk} from the request IP, using the fraud-grade geoip enrichment. The IP
    is used then discarded — only the booleans/label are returned. Empty (allow) when unavailable."""
    if request is None:
        return {"bot_suspect": False, "geo_risk": "low"}
    try:
        ip = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip() or \
             (request.client.host if request.client else "")
        from src.app.services.geoip import enrich_ip
        net = enrich_ip(ip) or {}
        return {"bot_suspect": bool(net.get("is_hosting") or net.get("is_vpn") or net.get("is_tor")),
                "geo_risk": str(net.get("geo_risk") or "low")}
    except Exception:
        return {"bot_suspect": False, "geo_risk": "low"}


def _emit_confirm_trace(db, order_id: str, verdict: Dict[str, Any]) -> None:
    """Best-effort: record a redraft-abuse WATCH on the decision trace (escalate = proceed but surfaced to
    governance). Never raises into the buyer flow."""
    try:
        from src.app.services.decision_log import log_trace_event
        log_trace_event(trace_id=None, event_type="redraft_abuse_watch", source_type="agent",
                        source_id="Procurement_Fraud_Agent", target_type="order", target_id=str(order_id),
                        payload=verdict, durable=True)
    except Exception:
        pass


@router.post("/cases/confirm-cart")
def confirm_cart(body: ConfirmCartBody, request: Request = None) -> Dict[str, Any]:
    """GATE 1 at the CART-CONFIRMATION boundary (buyer action — no operator role): materialize the confirmed
    cart's SHORTFALL lines into durable procurement cases (one per supplier group), IDEMPOTENTLY keyed on
    order_id — a double-submitted confirm returns the SAME cases, never duplicates. No supplier is contacted
    (each case waits at GATE 1). This is the buyer-facing twin of /cases/from-order; under
    FULFILLMENT_DEFER_TO_CART the recommend stage only PREVIEWED the split, so this is where intent becomes
    a durable case. Fully-in-stock lines are fulfilled from stock and create no case."""
    from src.app.security.rate_limit import consume_fixed_window_limit
    from src.app.security.buyer_principal import resolve_buyer_principal
    from src.app.services.fulfillment.cart_commitment import materialize_cases_for_order, supersede_order
    principal = resolve_buyer_principal(request, supplied_uid=body.uid)
    buyer_uid = principal.subject if principal else str(body.uid or "")
    # anti-abuse: bound confirm/amend churn per buyer (cost + security control). Fail-open if the limiter
    # backend is down (the limiter itself degrades gracefully); over-limit → 429.
    if not consume_fixed_window_limit(key=f"confirm_cart:{buyer_uid}", limit=_CONFIRM_RATE_PER_MIN, window_sec=60):
        raise HTTPException(status_code=429, detail="confirm_cart_rate_limited")
    # Address validation at GATE 1: a supplier RFQ that carries an unshippable ship_to produces a
    # case that can never fulfil. Reject an unusable ship_to here (only when one is supplied).
    _ship_to = (body.requirements or {}).get("ship_to") if isinstance(body.requirements, dict) else None
    if _ship_to:
        from src.app.services.address_validation import validate_address
        _sv = validate_address(_ship_to)
        if _sv.get("severity") == "reject":
            raise HTTPException(status_code=422, detail={"message": "invalid_ship_to", "reason": _sv.get("reason")})
    raw_lines = ([x.model_dump() for x in body.lines] if body.lines
                 else fos.parse_order_lines(body.query or ""))
    if not raw_lines:
        raise HTTPException(status_code=422, detail="no_order_lines")
    with db_session() as db:
        resolved = fos.resolve_line_skus(db, raw_lines)
        if not resolved:
            raise HTTPException(status_code=422, detail="no_order_lines_resolved")
        # stamp CURRENT stock per resolved SKU so shortfall is real (canonical batch read; best-effort —
        # an unreadable stock level defaults to 0 → the line sources, never silently drops).
        try:
            from src.app.services.inventory_query_service import batch_stock_levels
            stock = batch_stock_levels([str(l.get("item_ref")) for l in resolved if l.get("item_ref")])
        except Exception:
            stock = {}
        for l in resolved:
            sku = str(l.get("item_ref") or "")
            requested = int(l.get("requested_qty") or 0)
            submitted_source_qty = (
                max(0, min(requested, int(l["source_qty"])))
                if l.get("source_qty") is not None
                else None
            )
            try:
                from src.app.services.multi_location_availability import (
                    combined_availability, stock_by_location)
                locations = stock_by_location(db, [sku])
                from src.app.platform.store_profile import profile_slot
                preferred = str(
                    profile_slot("default_fulfillment_location", default="") or "").strip() or None
                aggregate = int(stock.get(sku, 0))
                by_location = locations.get(sku) or {
                    str(preferred or "aggregate"): aggregate
                }
                combined = combined_availability(
                    sku, requested, by_location=by_location,
                    preferred_location=(preferred if locations.get(sku) else None))
                observed_atp = int(combined["total_in_network"])
                calculated_shortfall = int(combined["supplier_rfq_qty"])
                combined["observed_atp"] = observed_atp
                combined["calculated_shortfall"] = calculated_shortfall
                combined["approved_source_override"] = submitted_source_qty
                combined["source_override_authority"] = (
                    "buyer_confirm_cart" if submitted_source_qty is not None else None
                )
                combined["source_override_reason"] = (
                    "confirmed_preview_source_qty" if submitted_source_qty is not None else None
                )
                l["availability"] = combined
                l["in_stock"] = observed_atp
                l["source_qty"] = (
                    submitted_source_qty
                    if submitted_source_qty is not None
                    else calculated_shortfall
                )
            except Exception:
                if l.get("in_stock") in (None, 0):
                    l["in_stock"] = int(stock.get(sku, 0))
        # supersede=True → buyer is amending a confirmed order: retire the active pre-send cases + re-source.
        if body.supersede:
            # NETWORK-AWARE churn brake: amendment-churn spins up supplier RFQ redrafts (a DDoS vector). Combine
            # the per-PR amendment cap with the fraud-grade ASN/GeoIP flags — a datacenter/VPN/Tor or high-geo
            # source over the cap is BLOCKED as suspected abuse; a normal source over the cap is throttled to a
            # human; early churn from a hostile source is escalated (watched). Buyer-mind-change stays smooth.
            from src.app.services.fulfillment.cart_commitment import count_amendments
            from src.app.services.fulfillment.procurement_fraud_signals import assess_redraft_abuse
            _net = _client_network(request)
            _verdict = assess_redraft_abuse(amendment_count=count_amendments(db, body.order_id),
                                            bot_suspect=_net["bot_suspect"], geo_risk=_net["geo_risk"])
            if _verdict["action"] == "block":
                raise HTTPException(status_code=403, detail={"error": "redraft_abuse_suspected", **_verdict})
            if _verdict["action"] == "throttle":
                raise HTTPException(status_code=429, detail={"error": "amendment_cap_exceeded", **_verdict})
            if _verdict["action"] == "escalate":
                _emit_confirm_trace(db, body.order_id, _verdict)  # watch, but let the buyer proceed
            result = supersede_order(db, order_id=body.order_id, lines=resolved, uid=buyer_uid,
                                     trace_id=body.trace_id, requirements=body.requirements)
        else:
            result = materialize_cases_for_order(db, order_id=body.order_id, lines=resolved,
                                                 uid=buyer_uid, trace_id=body.trace_id,
                                                 requirements=body.requirements)
        _notify_from_confirm(db, result)
    return result


def _notify_from_confirm(db, result: Dict[str, Any]) -> None:
    """Emit an operator notification when a confirm/supersede actually changed something (best-effort)."""
    try:
        from src.app.services.fulfillment.notifications import notify
        ref = result.get("order_group_id")
        if result.get("status") == "superseded":
            created = (result.get("created") or {}).get("case_count") or 0
            notify(db, kind="order_superseded", ref=ref,
                   summary=f"Order amended: retired {len(result.get('superseded') or [])} request(s), "
                           f"created {created} new sourcing case(s).")
        elif result.get("status") == "operator_required":
            notify(db, kind="operator_required", ref=ref,
                   summary="Buyer amended an order whose supplier was already contacted — operator action needed.")
        elif result.get("amend_required"):
            notify(db, kind="amend_required", ref=ref,
                   summary="Buyer re-confirmed an order with different items — amendment pending.")
        elif int(result.get("case_count") or 0) > 0 and not result.get("idempotent"):
            notify(db, kind="cases_materialized", ref=ref,
                   summary=f"New cart confirmation: {result.get('case_count')} sourcing case(s) created.")
    except Exception:
        pass


class NotificationsSeenBody(BaseModel):
    ids: Optional[list[str]] = None   # specific ids to mark seen; None → mark ALL unseen seen


@router.get("/notifications")
def get_notifications(unseen_only: bool = Query(default=False), limit: int = Query(default=50),
                      role: str = Depends(require_role(_OPERATOR))) -> Dict[str, Any]:
    """The operator notification feed (newest first) + the unseen badge count — polled by the admin queue."""
    from src.app.services.fulfillment.notifications import list_notifications, unseen_count
    with db_session() as db:
        return {"notifications": list_notifications(db, unseen_only=unseen_only, limit=limit),
                "unseen": unseen_count(db)}


@router.post("/notifications/seen")
def mark_notifications_seen(body: NotificationsSeenBody,
                           role: str = Depends(require_role(_OPERATOR))) -> Dict[str, Any]:
    """Mark notifications seen (given ids, or ALL unseen when ids omitted)."""
    from src.app.services.fulfillment.notifications import mark_seen
    with db_session() as db:
        return {"marked": mark_seen(db, ids=body.ids)}


class SupersedeCaseBody(BaseModel):
    reason: str = "operator_amendment"


@router.post("/cases/{case_id}/supersede")
def supersede_case(case_id: str, body: SupersedeCaseBody,
                   role: str = Depends(require_role(_OPERATOR))) -> Dict[str, Any]:
    """Operator retires a single case — including a POST-SEND one (a supplier was already emailed) that the
    buyer's confirm-cart flagged operator_required. Records the void draft hash (late quotes for it are
    quarantined) and flags cancellation_advised so the operator notifies the supplier."""
    from src.app.services.fulfillment.cart_commitment import operator_supersede_case
    from src.app.services.fulfillment.notifications import notify
    with db_session() as db:
        out = operator_supersede_case(db, case_id=case_id, actor_id=str(role or "operator"), reason=body.reason)
        if not out.get("ok"):
            raise HTTPException(status_code=409, detail=out.get("reason") or "supersede_failed")
        try:
            notify(db, kind="case_superseded", ref=case_id,
                   summary=f"Case {case_id[:8]} superseded"
                           + (" — notify the supplier of the cancellation." if out.get("cancellation_advised") else "."))
        except Exception:
            pass
        return out


class SupplierEventBody(BaseModel):
    supplier_domain: str
    note: str
    kind: str = "general"         # lead_time_change | price_change | out_of_stock | back_in_stock | contact_change | general
    trace_id: Optional[str] = None


@router.post("/supplier-events")
def supplier_event(body: SupplierEventBody, role: str = Depends(require_role(_OPERATOR))) -> Dict[str, Any]:
    """Out-of-band supplier contact (operator records "supplier X phoned: lead time slipped / OOS / price
    changed"). Records it durably and FANS OUT a note to every open case for that supplier domain so the
    case journeys reflect reality. Never contacts anyone, never mutates an issued PO (a new fact is appended)."""
    from src.app.services.fulfillment.notifications import notify
    from src.app.services.fulfillment.supplier_events import record_supplier_event
    with db_session() as db:
        out = record_supplier_event(db, supplier_domain=body.supplier_domain, kind=body.kind,
                                    note=body.note, actor_id=str(role or "operator"))
        if out.get("event_id"):
            try:
                notify(db, kind="supplier_oob", ref=out.get("domain"),
                       summary=f"Supplier {out.get('domain')} reported {out.get('kind')} — "
                               f"{len(out.get('affected_cases') or [])} open case(s) affected.")
            except Exception:
                pass
        return out


class CommitBody(BaseModel):
    uid: Optional[str] = None
    email: Optional[str] = None   # optional buyer email → bounded-autonomy status reply (flag-gated)


@router.post("/cases/{case_id}/commit")
def commit(case_id: str, body: CommitBody, request: Request) -> Dict[str, Any]:
    """GATE 1: the BUYER commits (places the order / requests sourcing). No operator role required —
    this is the buyer's own action; only now may a supplier be engaged."""
    from src.app.security.buyer_principal import assert_case_owner, resolve_buyer_principal
    principal = resolve_buyer_principal(request, supplied_uid=body.uid)
    buyer_uid = principal.subject if principal else str(body.uid or "")
    with db_session() as db:
        assert_case_owner(db, case_id, principal)
        res = fwf.transition(db, case_id=case_id, event="buyer_committed", actor=Actor(ActorType.BUYER, buyer_uid),
                             reason_code="buyer_commitment")
        _raise_if_failed(res)
        if _auto_draft_on_commit_enabled():
            try:
                cur = fwf.repository.current_version(db, case_id)
                sj = cur.state_json if cur and isinstance(cur.state_json, dict) else {}
                avail = sj.get("availability") if isinstance(sj.get("availability"), dict) else {}
                item_ref = str(avail.get("item_ref") or "").strip()
                qty = int(avail.get("shortfall") or avail.get("requested_qty") or 0)
                if item_ref and qty > 0:
                    try:
                        # Workflow transitions commit their own bitemporal state before emitting audit.
                        # Draft in an independent session so a provider/evidence failure cannot poison the
                        # already-committed buyer transition, and never wrap the workflow in a savepoint.
                        with db_session() as draft_db:
                            draft_result, _draft = fdraft.draft_and_record(
                                draft_db, case_id=case_id, actor=_agent(), item_ref=item_ref, quantity=qty,
                                estimated_value_cents=0, trace_id=(cur.source_trace_id if cur else None))
                            _raise_if_failed(draft_result)
                    except Exception as exc:
                        from src.app.services.fulfillment.draft_retry import enqueue
                        enqueue(db, case_id=case_id, item_ref=item_ref, quantity=qty,
                                trace_id=(cur.source_trace_id if cur else None), error=exc)
                        from src.app.services.decision_log import log_trace_event
                        log_trace_event(trace_id=(cur.source_trace_id if cur else None),
                                        event_type="supplier_rfq_draft_retry_queued", source_type="agent",
                                        source_id="Procurement_Agent", target_type="case", target_id=case_id,
                                        payload={"case_id": case_id, "item_ref": item_ref,
                                                 "quantity": qty, "status": "pending_retry"})
            except Exception as exc:
                import logging
                logging.getLogger(__name__).exception("auto-draft preparation failed for case %s", case_id)
        # bounded autonomy: auto-send the claim-safe "thanks, sourcing" status to the buyer (flag-gated;
        # no human approval needed because it makes no commitment). Best-effort.
        if body.email:
            from src.app.services.fulfillment.buyer_reply import send_buyer_status
            try:
                send_buyer_status(db, case_id, to_email=body.email)
            except Exception:
                pass
        return _case_view(db, case_id, for_operator=False)


class NotifyBuyerBody(BaseModel):
    to_email: str


@router.post("/cases/{case_id}/notify-buyer")
def notify_buyer(case_id: str, body: NotifyBuyerBody,
                 role: str = Depends(require_role(_OPERATOR))) -> Dict[str, Any]:
    """Operator-triggered buyer status notification (claim-safe, commitment-free). force=True so it sends
    even if the auto-reply flag is off — an explicit human action."""
    from src.app.services.fulfillment.buyer_reply import send_buyer_status
    with db_session() as db:
        result = send_buyer_status(db, case_id, to_email=body.to_email, force=True)
        return {**_case_view(db, case_id, for_operator=True), "buyer_notification": result}


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


def _approval_tiers_enabled() -> bool:
    return str(os.getenv("FULFILLMENT_APPROVAL_TIERS_ENABLED", "0")).strip().lower() in ("1", "true", "yes", "on")


def _budget_gate_enabled() -> bool:
    return str(os.getenv("FULFILLMENT_BUDGET_GATE_ENABLED", "0")).strip().lower() in ("1", "true", "yes", "on")


def _case_category(db, case_id: str) -> str:
    """The budget category for a case — the buyer's use_case (from requirements), else 'default'."""
    try:
        cur = fwf.repository.current_version(db, case_id)
        reqs = (cur.state_json.get("requirements") or {}) if cur and isinstance(cur.state_json, dict) else {}
        return str(reqs.get("use_case") or "default").strip().lower() or "default"
    except Exception:
        return "default"


def _case_spend_cents(db, case_id: str) -> Optional[int]:
    """The spend this case commits to a supplier (the approval-gate value): the wholesale cost from economics,
    else the draft's estimated value. Returns None when the spend is UNKNOWN (no economics + no estimate) — the
    caller must fail CLOSED, never treat unknown as $0 (which would slip a high-value send past a low tier)."""
    try:
        from src.app.services.fulfillment import economics as _feco
        econ = _feco.from_case(db, case_id) or {}
        sc = int(econ.get("supplier_cost_cents") or 0)
        if sc > 0:
            return sc
    except Exception:
        pass
    try:
        cur = fwf.repository.current_version(db, case_id)
        scope = ((cur.state_json.get("draft") or {}).get("commercial_scope") or {}) if cur and isinstance(cur.state_json, dict) else {}
        est = scope.get("estimated_value_cents")
        if est is not None:
            v = int(est)
            if v > 0:
                return v
    except Exception:
        pass
    return None


# D7 (budget cap bypass): the previous tuple listed "PO_PROPOSED"/"PO_ISSUED" which are NOT states
# in domain.py — so cases sitting in PROCUREMENT_APPROVAL_REQUIRED / PROCUREMENT_IN_PROGRESS were
# NOT counted as committed spend, and the cumulative budget cap could be bypassed (two cases each
# under the cap but jointly over). Use the REAL post-approval states.
_COMMITTED_SPEND_STATES = ("APPROVED_TO_SEND", "QUOTE_SENT", "QUOTE_RECEIVED", "QUOTE_VALIDATED",
                           "OPTIONS_READY", "SELECTED", "PROCUREMENT_APPROVAL_REQUIRED",
                           "PROCUREMENT_IN_PROGRESS", "READY_TO_SHIP", "PARTIALLY_READY", "COMPLETED")


def _category_committed_cents(db, category: str, *, exclude_case_id: str) -> int:
    """Spend already COMMITTED this period for a budget category — the sum over OTHER cases in that category
    that have passed the approval gate (APPROVED_TO_SEND and beyond, excluding superseded/rejected). Makes the
    budget gate CUMULATIVE: two separate cases can't each slip under the cap while together breaching it."""
    total = 0
    try:
        rows = fwf.repository.list_cases(db) or []
    except Exception:
        return 0
    for c in rows:
        if not isinstance(c, dict):
            continue
        cid = c.get("case_id")
        if not cid or str(cid) == str(exclude_case_id):
            continue
        if str(c.get("status")) not in _COMMITTED_SPEND_STATES:
            continue
        if _case_category(db, cid) != str(category):
            continue
        spend = _case_spend_cents(db, cid)
        if spend and spend > 0:
            total += int(spend)
    return total


@router.post("/cases/{case_id}/request-approval")
def request_approval(case_id: str, role: str = Depends(require_role(_OPERATOR))) -> Dict[str, Any]:
    from src.app.services.fulfillment.approval_policy import required_approval_tier
    from src.app.services.fulfillment.budget_gate import budget_status
    with db_session() as db:
        res, approval_id = fdraft.request_supplier_approval(db, case_id=case_id, actor=_agent())
        _raise_if_failed(res)
        # enterprise gates: WHICH approver tier this spend requires + whether it fits the category budget.
        # Both recorded for audit + surfaced so the operator routes correctly; enforced at the send gate
        # when their flags are on (default OFF preserves behaviour).
        spend = _case_spend_cents(db, case_id)
        category = _case_category(db, case_id)
        if spend is None:
            # surface the unknown explicitly so the operator prices the case; the send gate will block it
            tier = {"tier": "blocked", "min_level": 99, "value_cents": None, "reason": "spend_unknown"}
            budget = {"within_budget": False, "reason": "spend_unknown", "category": category}
        else:
            committed = _category_committed_cents(db, category, exclude_case_id=case_id)
            tier = required_approval_tier(spend)
            budget = budget_status(spend, category=category, committed_cents=committed)
        try:
            from src.app.services.decision_log import log_trace_event
            cur = fwf.repository.current_version(db, case_id)
            log_trace_event(trace_id=(cur.source_trace_id if cur else None), event_type="approval_gates",
                            source_type="agent", source_id="Approval_Policy_Agent", target_type="fulfillment_case",
                            target_id=case_id, payload={"tier": tier, "budget": budget}, durable=True)
        except Exception:
            pass
        auto = _attempt_autonomous_send(db, case_id)
        return {**_case_view(db, case_id, for_operator=True), "approval_id": approval_id,
                "approval_required_tier": tier, "budget_status": budget,
                "autonomous_send": {"action": auto.action, "reason": auto.reason,
                                    "provider_ref": auto.provider_ref}}


# ── Phase 3: buyer qualification (human ↔ buyer) BEFORE any supplier contact ──
@router.post("/cases/{case_id}/start-qualification")
def start_qualification(case_id: str, role: str = Depends(require_role(_OPERATOR))) -> Dict[str, Any]:
    """Open a buyer-clarification room (escalation room) seeded with the case context and mark the case
    awaiting qualification — the human confirms the buyer is serious before any supplier is contacted."""
    from src.app.routers.escalation_room import create_incident_record
    from src.app.services.fulfillment import buyer_qualification as fbq
    with db_session() as db:
        cur = fwf.repository.current_version(db, case_id)
        if cur is None:
            raise HTTPException(status_code=404, detail="case not found")
        av = (cur.state_json.get("availability") or {}) if isinstance(cur.state_json, dict) else {}
        room = create_incident_record(
            case_id=case_id, trace_id=cur.source_trace_id, reason="buyer_qualification",
            context={"kind": "buyer_qualification", "item_ref": av.get("item_ref"),
                     "requested_qty": av.get("requested_qty"), "shortfall": av.get("shortfall")},
            created_by=role, title="Buyer qualification: confirm bulk intent")
        res = fbq.request_qualification(db, case_id=case_id, actor=_agent(),
                                        room_ref=(room or {}).get("incident_id"))
        _raise_if_failed(res)
        return {**_case_view(db, case_id, for_operator=True), "qualification_room": room}


class QualifyBody(BaseModel):
    qualified: bool
    notes: Optional[str] = None


@router.post("/cases/{case_id}/qualify")
def qualify(case_id: str, body: QualifyBody, role: str = Depends(require_role(_OPERATOR))) -> Dict[str, Any]:
    """HUMAN records the qualification verdict after talking to the buyer: qualified → supplier contact is
    permitted; not → the case ends (BUYER_DECLINED) and no supplier is ever contacted."""
    human = Actor(ActorType.HUMAN_OPERATOR, role)
    from src.app.services.fulfillment import buyer_qualification as fbq
    with db_session() as db:
        cur = fwf.repository.current_version(db, case_id)
        room_ref = ((cur.state_json.get("qualification") if cur else None) or {}).get("room_ref")
        res = fbq.record_qualification(db, case_id=case_id, actor=human, qualified=body.qualified,
                                       notes=body.notes, room_ref=room_ref)
        _raise_if_failed(res)
        return _case_view(db, case_id, for_operator=True)


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
def dispatch(case_id: str, body: DispatchBody, role: str = Depends(require_role(_OPERATOR)),
             subj: OperatorSubject = Depends(operator_subject)) -> Dict[str, Any]:
    """GATE 2: the HUMAN approves + sends. approval_granted then the hash-checked send. When approval tiers
    are enabled, an approver below the spend's required tier is REJECTED (escalate to the right authority)."""
    human = _operator_actor(role, subj)
    with db_session() as db:
        if _approval_tiers_enabled() or _budget_gate_enabled():
            _spend = _case_spend_cents(db, case_id)
            if _spend is None:
                # FAIL CLOSED: a send whose value can't be determined must NOT slip through as $0 — block it
                # so a human prices the case before it clears any gate.
                raise HTTPException(status_code=409, detail={
                    "error": "spend_unknown",
                    "reason": "cannot determine case spend (no economics + no estimate) — price the case before sending"})
            _category = _case_category(db, case_id)
            if _approval_tiers_enabled():
                from src.app.services.fulfillment.approval_policy import approver_can_clear
                verdict = approver_can_clear(role, _spend)
                if not verdict["ok"]:
                    raise HTTPException(status_code=403, detail={"error": "approval_tier_insufficient", **verdict})
            if _budget_gate_enabled():
                # KNOWN RACE (P0-1g, budget gate is flag-off by default): committed-spend is a SUM
                # over OTHER cases and the commit is a transition on THIS case, so two concurrent
                # same-category approvals each exclude the other, each pass the cap, and cumulative
                # spend can breach it. The correct fix is a CATEGORY-level lock spanning this
                # check + the approval_granted transition (SELECT ... FOR UPDATE on a per-category
                # budget row, or a Postgres advisory lock) — deliberately NOT the permanent
                # slot-reservation used for refunds, which would block the category forever. Left as
                # a documented limitation until the gate is enabled + real category locking lands;
                # human-paced approvals make live occurrence unlikely in the meantime.
                from src.app.services.fulfillment.budget_gate import budget_status
                committed = _category_committed_cents(db, _category, exclude_case_id=case_id)
                b = budget_status(_spend, category=_category, committed_cents=committed)
                if not b["within_budget"]:
                    raise HTTPException(status_code=403, detail={"error": "over_budget", **b})
        _raise_if_failed(fwf.transition(db, case_id=case_id, event="approval_granted", actor=human,
                                        reason_code="human_approved"))
        res = fec.send_approved(db, case_id=case_id, actor=human, approval_content_hash=body.content_hash)
        _raise_if_failed(res)
        return _case_view(db, case_id, for_operator=True)


class DemoReplyBody(BaseModel):
    scenario: str = "full_quote"
    requested_qty: int = 6


class QuarantineDispositionBody(BaseModel):
    action: str
    note: Optional[str] = None


class EvidencePurposeBody(BaseModel):
    purpose: str


class LegalHoldBody(BaseModel):
    enabled: bool
    purpose: str


@router.post("/email/inbox/{inbox_id}/evidence/read")
def read_inbound_evidence(
    inbox_id: str,
    body: EvidencePurposeBody,
    role: str = Depends(require_role([ROLE_OWNER])),
    subj: OperatorSubject = Depends(operator_subject),
) -> Dict[str, Any]:
    """Explicit owner-only decrypt; the read is committed to the evidence audit ledger."""
    if not body.purpose.strip():
        raise HTTPException(status_code=400, detail="purpose_required")
    from src.app.services.inbound_email_evidence import load_raw_evidence

    actor_id = (getattr(subj, "user_id", "") or "").strip() or f"key:{role}"
    with db_session() as db:
        row = db.execute(
            __import__("sqlalchemy").text(
                "SELECT tenant_id, raw_evidence_ref FROM inbound_email_inbox WHERE id=:id"
            ),
            {"id": inbox_id},
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="inbound_email_not_found")
        try:
            evidence = load_raw_evidence(
                db,
                tenant_id=str(row[0]),
                evidence_ref=str(row[1]),
                actor_id=actor_id,
                purpose=body.purpose.strip(),
                inbox_id=inbox_id,
            )
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"inbox_id": inbox_id, "evidence": evidence}


@router.post("/email/inbox/{inbox_id}/evidence/legal-hold")
def legal_hold_inbound_evidence(
    inbox_id: str,
    body: LegalHoldBody,
    role: str = Depends(require_role([ROLE_OWNER])),
    subj: OperatorSubject = Depends(operator_subject),
) -> Dict[str, Any]:
    if not body.purpose.strip():
        raise HTTPException(status_code=400, detail="purpose_required")
    from src.app.services.inbound_email_evidence import set_legal_hold

    actor_id = (getattr(subj, "user_id", "") or "").strip() or f"key:{role}"
    with db_session() as db:
        row = db.execute(
            __import__("sqlalchemy").text(
                "SELECT tenant_id, raw_evidence_ref FROM inbound_email_inbox WHERE id=:id"
            ),
            {"id": inbox_id},
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="inbound_email_not_found")
        try:
            set_legal_hold(
                db,
                tenant_id=str(row[0]),
                evidence_ref=str(row[1]),
                enabled=body.enabled,
                actor_id=actor_id,
                purpose=body.purpose.strip(),
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"inbox_id": inbox_id, "legal_hold": body.enabled}


@router.get("/email/enrichment/jobs")
def email_enrichment_jobs(
    status: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    role: str = Depends(require_role([ROLE_OWNER])),
) -> Dict[str, Any]:
    with db_session() as db:
        where = "WHERE enrichment_status=:status" if status else ""
        rows = db.execute(
            __import__("sqlalchemy").text(
                "SELECT id, tenant_id, provider, provider_message_id, enrichment_status, "
                "enrichment_attempts, enrichment_error, updated_at FROM inbound_email_inbox "
                f"{where} ORDER BY updated_at DESC LIMIT :limit"
            ),
            {"status": status, "limit": limit},
        ).fetchall()
        return {
            "jobs": [
                {
                    "inbox_id": row[0], "tenant_id": row[1], "provider": row[2],
                    "provider_message_id": row[3], "status": row[4],
                    "attempts": row[5], "error": row[6], "updated_at": row[7],
                }
                for row in rows
            ]
        }


@router.post("/email/enrichment/jobs/{inbox_id}/replay")
def replay_email_enrichment(
    inbox_id: str,
    body: EvidencePurposeBody,
    role: str = Depends(require_role([ROLE_OWNER])),
    subj: OperatorSubject = Depends(operator_subject),
) -> Dict[str, Any]:
    if not body.purpose.strip():
        raise HTTPException(status_code=400, detail="purpose_required")
    actor_id = (getattr(subj, "user_id", "") or "").strip() or f"key:{role}"
    with db_session() as db:
        row = db.execute(
            __import__("sqlalchemy").text(
                "SELECT tenant_id, enrichment_status, raw_evidence_ref "
                "FROM inbound_email_inbox WHERE id=:id"
            ),
            {"id": inbox_id},
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="inbound_email_not_found")
        if str(row[1]) not in {"dead_lettered", "enqueue_failed"}:
            raise HTTPException(status_code=409, detail="enrichment_job_not_replayable")
        from src.app.services.inbound_email_evidence import _audit
        from src.app.tasks.email_enrichment_tasks import enrich_inbound_email

        _audit(
            db,
            tenant_id=str(row[0]),
            inbox_id=inbox_id,
            evidence_id=str(row[2]).split(":")[1],
            action="enrichment_replayed",
            actor_id=actor_id,
            purpose=body.purpose.strip(),
        )
        db.execute(
            __import__("sqlalchemy").text(
                "UPDATE inbound_email_inbox SET enrichment_status='queued', "
                "enrichment_error=NULL, updated_at=CURRENT_TIMESTAMP WHERE id=:id"
            ),
            {"id": inbox_id},
        )
        try:
            enrich_inbound_email.apply_async(args=[inbox_id, str(row[0])], countdown=2)
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"enrichment_queue_unavailable:{exc}") from exc
        return {"inbox_id": inbox_id, "status": "queued"}


@router.post("/cases/{case_id}/quarantine-disposition")
def quarantine_disposition(
    case_id: str,
    body: QuarantineDispositionBody,
    role: str = Depends(require_role(_OPERATOR)),
    subj: OperatorSubject = Depends(operator_subject),
) -> Dict[str, Any]:
    """Resolve operator work without ever releasing the original quarantined message."""
    from src.app.services.inbound_quarantine_dispositions import (
        ALLOWED_ACTIONS,
        record_disposition,
    )

    if body.action not in ALLOWED_ACTIONS:
        raise HTTPException(status_code=400, detail="invalid_quarantine_disposition")
    if body.action in {"discard", "open_fresh_rfq"} and not str(body.note or "").strip():
        raise HTTPException(status_code=400, detail="disposition_note_required")
    with db_session() as db:
        cur = fwf.repository.current_version(db, case_id)
        if cur is None:
            raise HTTPException(status_code=404, detail="case not found")
        if cur.state != "SUPPLIER_RESPONSE_QUARANTINED":
            raise HTTPException(status_code=409, detail="case_not_quarantined")
        quarantine = dict((cur.state_json or {}).get("quarantine") or {})
        inbox_id = str(quarantine.get("inbox_id") or "")
        if not inbox_id:
            raise HTTPException(status_code=409, detail="quarantine_inbox_reference_missing")
        fresh_case_id = None
        if body.action == "open_fresh_rfq":
            fresh_case_id = fwf.open_case(
                db,
                buyer_uid_hash=None,
                source_trace_id=cur.source_trace_id,
                requested_by=role,
                tenant_id="default",
                state_json={
                    "reopened_from_quarantine": {
                        "case_id": case_id,
                        "inbox_id": inbox_id,
                        "reason": quarantine.get("reason"),
                    }
                },
            )
        actor_id = (getattr(subj, "user_id", "") or "").strip() or f"key:{role}"
        try:
            disposition = record_disposition(
                db,
                tenant_id="default",
                inbox_id=inbox_id,
                action=body.action,
                actor_id=actor_id,
                note=body.note,
                fresh_case_id=fresh_case_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {
            **_case_view(db, case_id, for_operator=True),
            "quarantine_disposition": disposition,
        }


@router.post("/cases/{case_id}/demo-reply")
def demo_reply(case_id: str, body: DemoReplyBody, role: str = Depends(require_role(_OPERATOR))) -> Dict[str, Any]:
    """DEMO-only (FULFILLMENT_DEMO_ENABLED): inject a deterministic supplier reply, correlate, parse."""
    if not _demo_enabled():
        raise HTTPException(status_code=403, detail="demo replies disabled")
    if body.scenario not in fsb.SCENARIOS:
        raise HTTPException(status_code=400, detail=f"unknown scenario; choose from {sorted(fsb.SCENARIOS)}")
    with db_session() as db:
        reply = fsb.generate_reply(case_ref=case_id, scenario=body.scenario, requested_qty=body.requested_qty)
        res = fec.receive_email_reply(
            db,
            case_id=case_id,
            email={
                "message_id": f"<{reply['provider_ref']}@{reply['sender_domain']}>",
                "from_addr": f"quotes@{reply['sender_domain']}",
                "reply_to": f"quotes@{reply['sender_domain']}",
                "subject": f"RFQ response for {case_id}",
                "body": reply["body"],
                "attachments": [],
                "external_sender": True,
                "spf_result": "pass",
                "dkim_result": "pass",
                "dmarc_result": "pass",
                "dmarc_fail": False,
                "vendor_domain": reply["sender_domain"],
            },
            sender_domain=reply["sender_domain"],
            provider_ref=reply["provider_ref"],
        )
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
    """Run the REAL pipeline for the authenticated request tenant: backfill source facts → analyze →
    persist. Operator-triggered so the demo shows live findings without waiting for the beat schedule."""
    from src.app.services import market_pipeline as mp
    from src.app.platform.tenant_context import current_tenant_id
    tenant_id = current_tenant_id()
    with db_session() as db:
        out = mp.run_pipeline(db, tenant_id=tenant_id)
        return {"tenant_id": tenant_id, "refreshed": out, "state": mp.state(db, tenant_id=tenant_id)}


@router.get("/market/state")
def market_state(role: str = Depends(require_role(_OPERATOR))) -> Dict[str, Any]:
    """The current request tenant's REAL findings — the live counterpart to /replay/state."""
    from src.app.services import market_pipeline as mp
    from src.app.platform.tenant_context import current_tenant_id
    tenant_id = current_tenant_id()
    with db_session() as db:
        return {"tenant_id": tenant_id, **mp.state(db, tenant_id=tenant_id)}


@router.get("/market/digest")
def market_digest(role: str = Depends(require_role(_OPERATOR))) -> Dict[str, Any]:
    """The operator's market brief — severity/type rollups + suggested focus from ACTIVE findings.
    Deterministic facts always; the (flag-gated, local-LLM) narrative only rewrites wording. Advisory
    only: read-only projection, nothing executes from it (deck M3 summarization within the LLM boundary)."""
    from src.app.services.market_digest import build_digest
    from src.app.platform.tenant_context import current_tenant_id
    with db_session() as db:
        return build_digest(db, tenant_id=current_tenant_id())


@router.get("/market/traffic-sources")
def market_traffic_sources(role: str = Depends(require_role(_OPERATOR))) -> Dict[str, Any]:
    """Marketing-BI: visits + conversions + conversion-rate PER CHANNEL (traffic source), plus the
    channel-performance findings — 'which campaign/channel actually drove the sale'. Fed by the
    utm/referrer/gclid captured at the consumer-signals ingest; the channel is an opaque label (no raw IP)."""
    from src.app.services.traffic_source import channel_breakdown
    with db_session() as db:
        return channel_breakdown(db)


@router.get("/market/network-breakdown")
def market_network_breakdown(role: str = Depends(require_role(_OPERATOR))) -> Dict[str, Any]:
    """BI + security view of the COARSE, non-PII network fingerprint ({asn, country, risk_tier}) carried on
    visit signals: visits + verified-human counts by COUNTRY (region segmentation), by ASN (cluster
    forensics), and by RISK_TIER. Never exposes a raw IP — the enrichment is coarsened at capture and the IP
    is dropped. `coverage` reports how many visits carry the fingerprint."""
    from src.app.services.traffic_source import network_breakdown
    with db_session() as db:
        return network_breakdown(db)


@router.get("/market/sales-response")
def market_sales_response(sku: str = Query(...), qty: int = Query(1, ge=1),
                          retail_cents: Optional[int] = Query(None),
                          supplier_cost_cents: Optional[int] = Query(None),
                          role: str = Depends(require_role(_OPERATOR))) -> Dict[str, Any]:
    """Answers "how do sales change as demand / inventory / margin change?" for one item. Assembles the
    three axes from the EXISTING intelligence — recent demand findings (market_analysis), the item's live
    availability, and its deal economics (when retail + supplier cost are known) — and runs the pure
    sales-response policy. Returns the recommended discount/price/promotion/reorder move WITH its rationale.
    Recommends only (nothing is applied); the discount is always clamped to the margin floor."""
    from src.app.services.sales_response_policy import assess_sales_response
    from src.app.services.availability_agent import assess_availability
    from src.app.services.fulfillment.economics import compute as econ_compute
    from src.app.services.market_analysis import load_recent_findings
    econ = None
    if retail_cents and supplier_cost_cents:
        econ = econ_compute(supplier_unit_cost_cents=supplier_cost_cents, retail_unit_cents=retail_cents, quantity=qty)
    avail = assess_availability([sku], qty)
    with db_session() as db:
        findings = load_recent_findings(db, limit=50)
    resp = assess_sales_response(demand_findings=findings, availability=avail, economics=econ)
    out = resp.as_dict()
    out["item_ref"] = sku
    out["inputs"] = {"availability": {k: avail.get(k) for k in ("in_stock", "shortfall", "requested_qty")},
                     "economics_known": econ is not None, "demand_findings_seen": len(findings or [])}
    return out


@router.get("/market/storefront-emphasis")
def market_storefront_emphasis(inventory_position: str = Query("balanced"),
                               role: str = Depends(require_role(_OPERATOR))) -> Dict[str, Any]:
    """M5 STOREFRONT lane — the demand-aware homepage/product copy angle (features | value | urgency).
    Computes the demand trend from recent findings + the given inventory posture and runs the policy, so
    the storefront leads with VALUE on a surplus, URGENCY on shippable rising demand, else neutral FEATURES.
    Recommends only — the storefront banner reads this behind its own flag; nothing is applied here."""
    from src.app.services.sales_response_policy import SalesSituation, classify_demand_trend, decide
    from src.app.services.market_analysis import load_recent_findings
    with db_session() as db:
        findings = load_recent_findings(db, limit=50)
    trend, conf = classify_demand_trend(findings)
    inv = str(inventory_position or "balanced").strip().lower()
    r = decide(SalesSituation(demand_trend=trend, inventory_position=inv))
    return {"messaging_emphasis": r.messaging_emphasis, "demand_trend": trend,
            "demand_confidence": conf, "inventory_position": r.situation.get("inventory_position"),
            "promotion_bias": r.promotion_bias, "rationale": r.rationale,
            "demand_findings_seen": len(findings or [])}


@router.get("/market/support-response")
def market_support_response(objection: Optional[str] = Query(None),
                            role: str = Depends(require_role(_OPERATOR))) -> Dict[str, Any]:
    """M5 SUPPORT lane — the pre-sales phrasing angle to counter the blocking objection (deck: price
    objections → shift to lifetime VALUE). Uses the explicit ``objection`` when given, else the dominant
    objection theme from recent findings. Returns the response angle + guidance; the support runtime renders
    APPROVED copy for that angle (never free-form). Recommends only."""
    from src.app.services.support_response_policy import objection_response, dominant_objection
    from src.app.services.market_analysis import load_recent_findings
    if objection:
        resp = objection_response(objection)
        return {**resp.as_dict(), "source": "explicit"}
    with db_session() as db:
        findings = load_recent_findings(db, limit=50)
    resp = objection_response(dominant_objection(findings))
    return {**resp.as_dict(), "source": "recent_findings", "objection_findings_seen": len(findings or [])}


@router.get("/market/history")
def market_history(entity_ref: Optional[str] = Query(None), limit: int = Query(100, ge=1, le=1000),
                   role: str = Depends(require_role(_OPERATOR))) -> Dict[str, Any]:
    """Deck Module-2 read surface — the persistent market memory: trend indicators, competitor snapshots,
    and offer-policy decisions (optionally for one entity_ref), newest first. Read-only."""
    from src.app.services.market_store import list_trend_indicators, list_competitor_snapshots, list_offer_policies
    with db_session() as db:
        return {"trend_indicators": list_trend_indicators(db, entity_ref=entity_ref, limit=limit),
                "competitor_snapshots": list_competitor_snapshots(db, entity_ref=entity_ref, limit=limit),
                "offer_policies": list_offer_policies(db, entity_ref=entity_ref, limit=limit)}


@router.get("/governance/pulse")
def governance_pulse(tenant_id: str = Query("default"),
                     role: str = Depends(require_role(_OPERATOR))) -> Dict[str, Any]:
    """Owner/governance VISIBILITY (deck Step 11): one read-only snapshot rolling the existing audit trails
    into four cards — signal & decision state, experiment health, policy & compliance, operational pressure.
    The owner observes WITHOUT becoming a runtime dependency (this writes nothing). ``tenant_id`` lets the
    pulse follow the view (e.g. the isolated 'replay-demo' tenant during the synthetic replay)."""
    from src.app.services.governance_pulse import governance_pulse as pulse
    with db_session() as db:
        return pulse(db, tenant_id=str(tenant_id or "default"))


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
        # never evaluate on fewer than 2 samples/arm — a 1-sample 'significance' would scale/auto-revert on noise.
        requested = int(body.min_samples) if body and body.min_samples else 30
        return ec.evaluate_now(db, experiment_id=_exp_id(body), min_samples=max(2, requested))


@router.post("/market/experiment/revert")
def experiment_revert(body: ExperimentBody = Body(default=ExperimentBody()),
                      role: str = Depends(require_role(_OPERATOR))) -> Dict[str, Any]:
    """The manual revert lever — stop the adaptation globally."""
    from src.app.services import experiment_console as ec
    with db_session() as db:
        return ec.revert(db, experiment_id=_exp_id(body))


class SelectBody(BaseModel):
    uid: Optional[str] = None
    option_id: str


@router.post("/cases/{case_id}/select-option")
def select_option(case_id: str, body: SelectBody, request: Request) -> Dict[str, Any]:
    """BUYER picks an offered option (no operator role — the buyer's own action)."""
    from src.app.security.buyer_principal import assert_case_owner, resolve_buyer_principal
    principal = resolve_buyer_principal(request, supplied_uid=body.uid)
    buyer_uid = principal.subject if principal else str(body.uid or "")
    with db_session() as db:
        assert_case_owner(db, case_id, principal)
        res = fopt.select_option(
            db,
            case_id=case_id,
            actor=Actor(ActorType.BUYER, buyer_uid),
            option_id=body.option_id,
        )
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
               role: str = Depends(require_role(_OPERATOR)),
               subj: OperatorSubject = Depends(operator_subject)) -> Dict[str, Any]:
    """HUMAN approves AND creates the PO (APPROVAL_REQUIRED → IN_PROGRESS → READY_TO_SHIP). Refused if
    the quote expired or the PO exceeds the approved scope. SANDBOX: records a PO ref, transmits nothing."""
    human = _operator_actor(role, subj)
    with db_session() as db:
        res = fpo.execute(db, case_id=case_id, actor=human, idempotency_key=body.idempotency_key,
                          today=body.today)
        _raise_if_failed(res)
        return _case_view(db, case_id, for_operator=True)


class GoodsReceiptBody(BaseModel):
    quantity: int


class InvoiceBody(BaseModel):
    quantity: int
    amount_cents: int


def _three_way_match_enabled() -> bool:
    return str(os.getenv("FULFILLMENT_THREE_WAY_MATCH_ENABLED", "0")).strip().lower() in ("1", "true", "yes", "on")


@router.post("/cases/{case_id}/record-receipt")
def record_receipt(case_id: str, body: GoodsReceiptBody,
                   role: str = Depends(require_role(_OPERATOR))) -> Dict[str, Any]:
    """Record goods receipt (received quantity) — the second leg of the 3-way match. SYSTEM (ASN/EDI 856)
    or operator. A self-loop: no state change, just the document the AP control reconciles."""
    with db_session() as db:
        res = fwf.transition(db, case_id=case_id, event="goods_receipt_recorded",
                             actor=Actor(ActorType.HUMAN_OPERATOR, role), reason_code="goods_receipt",
                             evidence={"quantity": int(body.quantity)},
                             state_patch={"goods_receipt": {"quantity": int(body.quantity)}})
        _raise_if_failed(res)
        return _case_view(db, case_id, for_operator=True)


@router.post("/cases/{case_id}/record-invoice")
def record_invoice(case_id: str, body: InvoiceBody,
                   role: str = Depends(require_role(_OPERATOR))) -> Dict[str, Any]:
    """Record the supplier invoice (quantity + amount) — the third leg of the 3-way match. SYSTEM (EDI 810)
    or operator. Self-loop; reconciled against the PO + goods receipt at completion."""
    with db_session() as db:
        res = fwf.transition(db, case_id=case_id, event="invoice_recorded",
                             actor=Actor(ActorType.HUMAN_OPERATOR, role), reason_code="invoice",
                             evidence={"quantity": int(body.quantity), "amount_cents": int(body.amount_cents)},
                             state_patch={"invoice": {"quantity": int(body.quantity),
                                                      "amount_cents": int(body.amount_cents)}})
        _raise_if_failed(res)
        return _case_view(db, case_id, for_operator=True)


@router.post("/cases/{case_id}/complete")
def complete_case(case_id: str, role: str = Depends(require_role(_OPERATOR)),
                  subj: OperatorSubject = Depends(operator_subject)) -> Dict[str, Any]:
    """HUMAN marks the order COMPLETED (READY_TO_SHIP → COMPLETED) — the journey's final act. When
    FULFILLMENT_THREE_WAY_MATCH_ENABLED, completion (payment) is GATED on PO = goods-receipt = invoice."""
    with db_session() as db:
        if _three_way_match_enabled():
            from src.app.services.fulfillment.three_way_match import match_for_case
            cur = fwf.repository.current_version(db, case_id)
            twm = match_for_case(cur.state_json if cur and isinstance(cur.state_json, dict) else {})
            if not twm["matched"]:
                raise HTTPException(status_code=409, detail={"error": "three_way_match_failed", **twm})
        res = fpo.complete(db, case_id=case_id, actor=_operator_actor(role, subj))
        _raise_if_failed(res)
        return _case_view(db, case_id, for_operator=True)


# ── GATE 3: post-commitment change-order / cancellation (the irreversibility ladder) ────────────────
def _change_order_enabled() -> bool:
    return str(os.getenv("FULFILLMENT_CHANGE_ORDER_ENABLED", "0")).strip().lower() in ("1", "true", "yes", "on")


class ProposeChangeBody(BaseModel):
    kind: str = "cancel"            # cancel | amend | new_linked
    reason: str = "buyer_change"
    refundable_to_buyer_cents: int = 0
    derived_pr_id: Optional[str] = None


class CancelBody(BaseModel):
    reason: str = "operator_authorised_cancellation"


@router.get("/cases/{case_id}/change-economics")
def change_economics(case_id: str, refundable_to_buyer_cents: int = Query(0),
                     role: str = Depends(require_role(_OPERATOR))) -> Dict[str, Any]:
    """GATE 3: the economics a human sees before authorising a post-commitment change — committed cost,
    restock fee, supplier penalty, net cancellation cost. Read-only; moves nothing."""
    from src.app.services.fulfillment import change_order as fco
    with db_session() as db:
        return fco.assess_for_case(db, case_id, refundable_to_buyer_cents=refundable_to_buyer_cents)


@router.post("/cases/{case_id}/propose-change")
def propose_change(case_id: str, body: ProposeChangeBody,
                   role: str = Depends(require_role(_OPERATOR))) -> Dict[str, Any]:
    """GATE 3 proposal: RECORD a post-commitment change request + its economics (no money moves, no state
    change). The original order is preserved; a human authorises any cancellation separately."""
    if not _change_order_enabled():
        raise HTTPException(status_code=403, detail={"error": "change_order_disabled"})
    from src.app.services.fulfillment import change_order as fco
    with db_session() as db:
        res = fco.propose_change(db, case_id=case_id, actor=Actor(ActorType.HUMAN_OPERATOR, role),
                                 kind=body.kind, reason=body.reason, derived_pr_id=body.derived_pr_id,
                                 assessment=fco.assess_for_case(db, case_id,
                                                                refundable_to_buyer_cents=body.refundable_to_buyer_cents))
        _raise_if_failed(res)
        return _case_view(db, case_id, for_operator=True)


@router.post("/cases/{case_id}/cancel")
def cancel_order(case_id: str, body: CancelBody = Body(default=CancelBody()),
                 role: str = Depends(require_role(_OPERATOR)),
                 subj: OperatorSubject = Depends(operator_subject)) -> Dict[str, Any]:
    """GATE 3: a HUMAN authorises cancellation of a COMMITTED order (PROCUREMENT_IN_PROGRESS/READY_TO_SHIP →
    CANCELLED). The domain guard makes this human-only — an agent can never fire it. The original order is
    preserved bitemporally; refund/restock EXECUTION stays behind FULFILLMENT_REFUND_ENABLED (no money moves)."""
    if not _change_order_enabled():
        raise HTTPException(status_code=403, detail={"error": "change_order_disabled"})
    from src.app.services.fulfillment import change_order as fco
    with db_session() as db:
        res = fco.authorize_cancellation(db, case_id=case_id, actor=_operator_actor(role, subj),
                                         reason=body.reason)
        _raise_if_failed(res)
        return _case_view(db, case_id, for_operator=True)


# ── Reliable outbound queue (Tier-1 #5): retry/dead-letter/855-ack operability ────────────────────
class AckBody(BaseModel):
    ack_ref: str = ""


def _replay_deferred_send_transitions(db, sent_rows: list) -> Dict[str, int]:
    """A background delivery only TRANSMITS; the case still sits in APPROVED_TO_SEND. Here we replay the
    EXACT transition that the human (or autonomous agent) already approved at dispatch time — recorded on the
    queue row — so a deferred send advances the case to QUOTE_SENT instead of stranding it. Idempotent: a case
    already advanced (or superseded) simply fails the guard and is counted as skipped, never re-fired."""
    advanced, skipped = 0, 0
    for row in (sent_rows or []):
        ev = str(row.get("transition_event") or "")
        a_type = str(row.get("actor_type") or "")
        cid = str(row.get("case_id") or "")
        if not (ev and a_type and cid):
            skipped += 1
            continue
        try:
            actor = Actor(ActorType(a_type), str(row.get("actor_id") or ""))
            res = fwf.transition(db, case_id=cid, event=ev, actor=actor, reason_code="deferred_send_delivered",
                                 evidence={"provider_ref": row.get("provider_ref", ""), "deferred": True},
                                 state_patch={"outbound": {"provider_ref": row.get("provider_ref", ""),
                                                           "content_hash": row.get("content_hash"), "status": "sent",
                                                           "transport": "queued"}})
            if getattr(res, "ok", False):
                advanced += 1
            else:
                skipped += 1  # case no longer in APPROVED_TO_SEND (e.g. superseded) — guard refused, by design
        except Exception:
            skipped += 1
    return {"advanced": advanced, "skipped": skipped}


@router.post("/outbound/process")
def outbound_process(role: str = Depends(require_role(_OPERATOR))) -> Dict[str, Any]:
    """Drive the durable outbound queue once — attempt every DUE pending send, backing off failures and
    dead-lettering exhausted ones. A deferred delivery then REPLAYS the approved transition so the case advances
    to QUOTE_SENT (no stranding). In production a worker calls this on a schedule; here an operator can too."""
    from src.app.services.fulfillment import outbound_queue as oq
    with db_session() as db:
        out = oq.process_pending(db)
        out["transitions"] = _replay_deferred_send_transitions(db, out.get("sent_rows") or [])
        return out


@router.get("/outbound/status")
def outbound_status(role: str = Depends(require_role(_OPERATOR))) -> Dict[str, Any]:
    """Queue health: counts by status + how many sent messages are still unacknowledged (no 855)."""
    from src.app.services.fulfillment import outbound_queue as oq
    with db_session() as db:
        return oq.queue_status(db)


@router.get("/outbound/dead-letters")
def outbound_dead_letters(role: str = Depends(require_role(_OPERATOR))) -> Dict[str, Any]:
    """The sends that exhausted their retries — operator triage queue."""
    from src.app.services.fulfillment import outbound_queue as oq
    with db_session() as db:
        return {"dead_letters": oq.dead_letters(db)}


@router.post("/cases/{case_id}/record-ack")
def outbound_record_ack(case_id: str, body: AckBody,
                        role: str = Depends(require_role(_OPERATOR))) -> Dict[str, Any]:
    """Record the supplier's acknowledgement (EDI 855) for the case's sent message — closes the send→ack loop.
    Resolves the message by the case's outbound content_hash. SYSTEM (855 inbound) or operator."""
    from src.app.services.fulfillment import outbound_queue as oq
    with db_session() as db:
        cur = fwf.repository.current_version(db, case_id)
        sj = cur.state_json if cur and isinstance(cur.state_json, dict) else {}
        content_hash = str((sj.get("outbound") or {}).get("content_hash") or "")
        if not content_hash:
            raise HTTPException(status_code=409, detail={"error": "no_outbound_to_ack"})
        r = oq.record_ack(db, idempotency_key=content_hash, ack_ref=body.ack_ref, case_id=case_id)
        if not r.get("acked"):
            # 409 when the message exists but isn't ackable yet (not sent); 404 only when truly absent.
            code = 404 if r.get("reason") == "not_found" else 409
            raise HTTPException(status_code=code, detail={"error": "ack_rejected", **r})
        return {"case_id": case_id, **r}
