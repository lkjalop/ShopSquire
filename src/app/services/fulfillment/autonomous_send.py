"""Autonomous RFQ send (agnostic CORE) — WS-C.

A flag-gated, SAFE-FIRST policy gate that decides whether an RFQ draft may be sent to a supplier WITHOUT
a human, or must ESCALATE to the human approval gate (GATE 2). An RFQ is non-binding — the send-cage
guarantees the body carries no price and no purchase-order commitment — so autonomous send is permissible,
but ONLY when EVERY guard passes:

    flag ON  ∧  not killed  ∧  recipient trusted (allowlist + KYV verified, risk ≤ medium)
    ∧  draft claim-safe  ∧  draft complete (WS-B)  ∧  confidence ≥ threshold
    ∧  estimated value ≤ cap  ∧  quantity ≤ cap  ∧  under the per-hour rate limit
    ∧  the adaptive_action_gate AUTHORIZES the send (fired at the workflow chokepoint)

Any failing guard → ESCALATE: the case is left at AWAITING_APPROVAL (already queued for the human by
request_supplier_approval) and a reason is returned. The function never changes state on escalate and
never raises — it FAILS CLOSED to escalate. The two state transitions it drives on the happy path are
AGENT-fired and DISTINCT from the human GATE 2 events, so the human-only send invariant is untouched and
the bitemporal trace records that the send was autonomous.

Config (all default-SAFE; autonomy is OFF until explicitly enabled):
    FULFILLMENT_AUTONOMOUS_RFQ              flag, default OFF
    FULFILLMENT_AUTONOMOUS_KILL_SWITCH     emergency stop, default OFF (ADAPTATION_KILL_SWITCH also honoured)
    FULFILLMENT_AUTONOMOUS_MIN_CONFIDENCE  default 0.8
    FULFILLMENT_AUTONOMOUS_MAX_VALUE_CENTS default 500000 ($5,000)
    FULFILLMENT_AUTONOMOUS_MAX_QTY         default 25
    FULFILLMENT_AUTONOMOUS_RATE_PER_HOUR   default 10

Vertical-blind: pure policy + workflow, no product vocabulary.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional

from src.app.services.fulfillment import workflow
from src.app.services.fulfillment.domain import Actor


@dataclass(frozen=True)
class SendDecision:
    action: str            # "sent" | "escalated" | "send_failed"
    reason: str            # machine-readable reason (e.g. "flag_off", "low_confidence", "autonomous_send")
    provider_ref: Optional[str] = None

    @property
    def sent(self) -> bool:
        return self.action == "sent"


def _truthy(v) -> bool:
    if isinstance(v, bool):
        return v
    return v is not None and str(v).strip().lower() in ("1", "true", "yes", "on")


def _flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return _truthy(raw)


def _flag_file_value(key: str):
    """Read one key from feature_flags.json (the governed runtime-toggle surface — flip it via the
    dual-control POST /api/v1/admin/flags, no redeploy). Best-effort; None on any error."""
    try:
        import json
        from src.app.config import get_settings
        with open(get_settings().feature_flags_path, "r", encoding="utf-8") as f:
            return json.load(f).get(key)
    except Exception:
        return None


def is_enabled() -> bool:
    """Autonomy is ON if the env flag OR the feature-flag file says so (either can enable; OFF by default)."""
    return _flag("FULFILLMENT_AUTONOMOUS_RFQ") or _truthy(_flag_file_value("FULFILLMENT_AUTONOMOUS_RFQ"))


def is_killed() -> bool:
    """Fail-SAFE kill: ANY kill source stops autonomy — the dedicated switch (env or flag file), the global
    adaptation kill switch, or the feature-flag file's top-level KILL_SWITCH."""
    return (_flag("FULFILLMENT_AUTONOMOUS_KILL_SWITCH") or _flag("ADAPTATION_KILL_SWITCH")
            or _truthy(_flag_file_value("FULFILLMENT_AUTONOMOUS_KILL_SWITCH"))
            or _truthy(_flag_file_value("KILL_SWITCH")))


def _num(name: str, default: float) -> float:
    try:
        v = os.getenv(name)
        return float(v) if v is not None and str(v).strip() != "" else float(default)
    except Exception:
        return float(default)


def _kyv_trusted(domain: str, tenant_id: str, kyv_fn: Optional[Callable]) -> bool:
    """A KYV record exists for the domain, is verified, and is not high/critical risk. Defaults to the
    real registry; injectable for tests. Any error → not trusted (fail closed)."""
    try:
        lookup = kyv_fn
        if lookup is None:
            from src.app.security.kyv_registry import lookup_vendor_by_domain as lookup
        rec = lookup(tenant_id=tenant_id, domain=domain)
        if not rec:
            return False
        status = str(rec.get("status") or "").strip().lower()
        risk = str(rec.get("risk_tier") or "").strip().lower()
        return status == "verified" and risk in ("low", "medium")
    except Exception:
        return False


def _trusted(domain: str, tenant_id: str, allowlist_fn: Optional[Callable], kyv_fn: Optional[Callable]) -> bool:
    if not domain:
        return False
    try:
        if allowlist_fn is not None and not allowlist_fn(domain):
            return False
    except Exception:
        return False
    return _kyv_trusted(domain, tenant_id, kyv_fn)


def _recent_autonomous_count(db, tenant_id: str) -> int:
    """Autonomous-send authorizations in the last hour (counts allow rows for the supplier_rfq_send action
    in the durable audit). Used for the per-hour rate limit. Any error → a high count (fail closed)."""
    try:
        from sqlalchemy import text
        since = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
        row = db.execute(
            text("SELECT COUNT(*) FROM adaptive_action_audit WHERE COALESCE(tenant_id,'default')=:t "
                 "AND action_type='supplier_rfq_send' AND decision='allow' AND created_at >= :since"),
            {"t": tenant_id, "since": since}).fetchone()
        return int(row[0]) if row else 0
    except Exception:
        return 10 ** 9  # cannot verify the rate → treat as over the limit → escalate


def maybe_autonomous_send(
    db,
    *,
    case_id: str,
    actor: Actor,
    confidence: float,
    estimated_value_cents: int,
    quantity: int,
    recipient_domain: Optional[str] = None,
    allowlist_fn: Optional[Callable] = None,
    kyv_fn: Optional[Callable] = None,
    transport: Optional[Any] = None,
    tenant_id: str = "default",
    now_iso: Optional[str] = None,
    trace_id: Optional[str] = None,
) -> SendDecision:
    """Decide + (when authorized) perform an autonomous RFQ send. Operates on a case already at
    AWAITING_APPROVAL. Returns a SendDecision; escalate leaves the case untouched for the human.

    When autonomy is ACTIVE, every escalation is recorded to the durable audit (decision='escalate' +
    reason) so the operator can SEE why autonomy held back; the send path is audited by the action-gate as
    decision='allow'. flag_off is NOT audited (it would write a row on every request while autonomy is off)."""
    # autonomy disabled → not a decision worth auditing; hand straight back to the human.
    if not is_enabled():
        return SendDecision("escalated", "flag_off")

    def escalate(reason: str) -> SendDecision:
        from src.app.services.adaptive_action_gate import record_decision
        record_decision(db, action_type="supplier_rfq_send", decision="escalate", reason=reason,
                        confidence=float(confidence or 0.0) if isinstance(confidence, (int, float)) else 0.0,
                        subject=getattr(actor, "id", None), target=case_id, tenant_id=tenant_id)
        return SendDecision("escalated", reason)

    try:
        if is_killed():
            return escalate("killed")

        cur = workflow.repository.current_version(db, case_id, tenant_id)
        draft = (cur.state_json.get("draft") if cur else None) or {}
        if not draft.get("content_hash"):
            return escalate("no_draft")

        domain = str(recipient_domain or draft.get("recipient_domain") or "").strip().lower()
        if not _trusted(domain, tenant_id, allowlist_fn, kyv_fn):
            return escalate("recipient_untrusted")

        # claim-safety: defense-in-depth (build_draft already enforced it against the resolved domain)
        from src.app.services.fulfillment.draft import claim_safety_reason
        cr = claim_safety_reason(str(draft.get("body") or ""), recipient_domain=domain)
        if cr is not None:
            return escalate(f"claim_unsafe:{cr}")

        comp = draft.get("completeness") or {}
        if not comp.get("complete", False):
            return escalate(f"incomplete:{comp.get('reason')}")

        try:
            conf = float(confidence)
        except Exception:
            conf = 0.0
        if conf < _num("FULFILLMENT_AUTONOMOUS_MIN_CONFIDENCE", 0.8):
            return escalate("low_confidence")
        if int(estimated_value_cents or 0) > int(_num("FULFILLMENT_AUTONOMOUS_MAX_VALUE_CENTS", 500000)):
            return escalate("over_value_cap")
        if int(quantity or 0) > int(_num("FULFILLMENT_AUTONOMOUS_MAX_QTY", 25)):
            return escalate("over_qty_cap")
        if _recent_autonomous_count(db, tenant_id) >= int(_num("FULFILLMENT_AUTONOMOUS_RATE_PER_HOUR", 10)):
            return escalate("rate_limited")

        # all guards passed → autonomous approval (the workflow's confidence gate routes this through the
        # adaptive_action_gate as action_type 'supplier_rfq_send': kill-switch + confidence + durable audit).
        appr = workflow.transition(
            db, case_id=case_id, event="approval_granted_autonomous", actor=actor,
            reason_code="autonomous_rfq_approved", confidence=conf,
            evidence={"content_hash": draft.get("content_hash"), "recipient_domain": domain,
                      "estimated_value_cents": int(estimated_value_cents or 0), "quantity": int(quantity or 0),
                      "guards": "flag,kill,trust,claim_safe,complete,confidence,value,qty,rate"},
            tenant_id=tenant_id, now_iso=now_iso, trace_id=trace_id)
        if not appr.ok:
            return escalate(f"gate:{appr.reason}")  # action-gate denied (killed/low_confidence/audit) → human

        from src.app.services.fulfillment import external_comms as ec
        res = ec.send_autonomous(db, case_id=case_id, actor=actor, transport=transport,
                                 tenant_id=tenant_id, now_iso=now_iso, trace_id=trace_id)
        if not res.ok:
            # the transport did not transmit → the case stays APPROVED_TO_SEND (a human can retry/send).
            return SendDecision("send_failed", res.reason)
        provider_ref = None
        try:
            cur2 = workflow.repository.current_version(db, case_id, tenant_id)
            provider_ref = ((cur2.state_json.get("outbound") if cur2 else None) or {}).get("provider_ref")
        except Exception:
            provider_ref = None
        return SendDecision("sent", "autonomous_send", provider_ref=provider_ref)
    except Exception:
        return escalate("error_fail_closed")
