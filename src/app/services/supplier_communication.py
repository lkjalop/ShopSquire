"""Supplier communication — draft-first, gate-enforced outbound (Track 4). CORE / vertical-blind.

Bounded autonomy in one module: the AI may DRAFT a supplier message freely (no consequence), but a
SEND happens only when ALL of these hold:
  1. allow_send is explicitly requested by the caller,
  2. the execution gate returns ALLOW for action "supplier_contact" (default is HUMAN_REVIEW — see
     action_authority_matrix SUP-04 — so an autonomous send is impossible without a deliberate rule),
  3. the recipient domain is on the trusted-supplier allowlist (defense in depth), and
  4. a real mailer is injected (the default NullMailer sends nothing).
Otherwise the draft is returned with a status explaining why it was held. Never raises, and never
sends on a non-ALLOW verdict. Message WORDING per vertical is FLAVOUR and lives in the profile slot
`supplier_message_templates`; this module carries only a neutral, vertical-blind fallback.
"""
from __future__ import annotations

import contextlib
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional

from src.app.ports.supplier_communication import NullMailer, SupplierMailer

# Neutral, vertical-blind fallback used only when a profile supplies no template for `kind`.
_GENERIC_TEMPLATE = {
    "subject": "{kind_title} request — {item}",
    "body": (
        "Hello {supplier_name},\n\n"
        "We would like to raise a {kind} regarding {item}.\n"
        "{details}\n\n"
        "Please reply to confirm. This message is a draft prepared for review.\n\n"
        "Regards,\n{sender_name}"
    ),
}


@dataclass
class SupplierDraft:
    kind: str
    supplier_name: str
    supplier_email: str
    subject: str
    body: str
    item: str = ""
    meta: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind,
            "supplier_name": self.supplier_name,
            "supplier_email": self.supplier_email,
            "subject": self.subject,
            "body": self.body,
            "item": self.item,
            "meta": dict(self.meta),
        }


class _Blank(dict):
    """format_map helper: unknown placeholders render blank instead of raising KeyError."""

    def __missing__(self, key: str) -> str:  # noqa: D401
        return ""


def _safe_format(template: str, fields: Dict[str, Any]) -> str:
    try:
        return str(template).format_map(_Blank(fields))
    except Exception:
        return str(template)


def draft_supplier_message(
    *,
    kind: str,
    supplier_name: str,
    supplier_email: str,
    item: str = "",
    details: str = "",
    sender_name: str = "ShopSquire",
    templates: Optional[Dict[str, Dict[str, str]]] = None,
    extra_fields: Optional[Dict[str, Any]] = None,
) -> SupplierDraft:
    """Produce a supplier-message DRAFT. Pure — no I/O, never sends. `templates` is the profile slot
    `supplier_message_templates` (flavour); a neutral fallback is used when a kind is absent."""
    k = str(kind or "message").strip().lower()
    tpl: Optional[Dict[str, str]] = None
    if isinstance(templates, dict):
        candidate = templates.get(k) or templates.get("default")
        if isinstance(candidate, dict):
            tpl = candidate
    tpl = tpl or _GENERIC_TEMPLATE

    fields: Dict[str, Any] = {
        "kind": k,
        "kind_title": k.replace("_", " ").title(),
        "supplier_name": supplier_name or "Supplier",
        "item": item or "",
        "details": details or "",
        "sender_name": sender_name or "ShopSquire",
    }
    if isinstance(extra_fields, dict):
        fields.update(extra_fields)

    subject = _safe_format(tpl.get("subject") or _GENERIC_TEMPLATE["subject"], fields).strip()
    body = _safe_format(tpl.get("body") or _GENERIC_TEMPLATE["body"], fields).strip()
    return SupplierDraft(
        kind=k,
        supplier_name=fields["supplier_name"],
        supplier_email=supplier_email or "",
        subject=subject,
        body=body,
        item=item or "",
    )


def _default_domain_trusted(email: str) -> bool:
    from src.app.services.supplier_domain_guard import extract_domain, is_trusted_supplier_domain
    return bool(is_trusted_supplier_domain(extract_domain(email) or ""))


def dispatch_supplier_message(
    *,
    draft: SupplierDraft,
    allow_send: bool = False,
    mailer: Optional[SupplierMailer] = None,
    decide_fn: Optional[Callable[..., Any]] = None,
    domain_trusted_fn: Optional[Callable[[str], bool]] = None,
    value_cents: int = 0,
    tenant_id: Optional[str] = None,
    actor: Optional[str] = None,
    from_email: Optional[str] = None,
    boundary_check_fn: Optional[Callable[..., Any]] = None,
    trace_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Decide-then-(maybe)-send. ALWAYS returns the draft. Never raises; never sends unless
    allow_send AND the MAESTRO boundary passes AND the gate ALLOWs supplier_contact AND the recipient
    domain is trusted AND a real mailer is bound. Returns {draft, sent, status, [verdict], [maestro],
    [send_result], reason}."""
    out: Dict[str, Any] = {"draft": draft.to_dict(), "sent": False, "status": "draft_only"}

    # Bounded-autonomy default: a draft is just a draft until a human/flow asks to send.
    if not allow_send:
        out["reason"] = "allow_send not requested — draft retained for human review"
        return out

    # 0) MAESTRO boundary (defense in depth, before the policy gate): the supplier-comms agent may
    # only invoke the dispatch tool within the suppliers scope. In 'block' mode a high/critical
    # violation raises MaestroViolationError (caught -> held); in 'audit' (default) it just records.
    if boundary_check_fn is None:
        try:
            from src.app.security.maestro_boundaries import record_agent_action as boundary_check_fn  # type: ignore[assignment]
            from src.app.services.decision_log import log_trace_event as _ss_log
        except Exception:
            boundary_check_fn, _ss_log = None, None
    else:
        _ss_log = None
    if boundary_check_fn is not None:
        _violations = None
        try:
            _violations = boundary_check_fn(
                agent_name="Supplier_Communication_Agent", tool_name="dispatch_supplier_message",
                data_scope="suppliers", value_usd=float(value_cents or 0) / 100.0,
                trace_id=trace_id, log_fn=_ss_log,
            )
        except Exception as _mexc:  # MaestroViolationError in 'block' mode -> hold the send
            out["status"] = "held_for_review"
            out["reason"] = f"maestro boundary violation: {str(_mexc)[:160]}"
            out["maestro"] = {"blocked": True}
            return out
        if _violations:
            out["maestro"] = {"violations": [getattr(v, "violation_type", "unknown") for v in _violations]}

    # 1) Gate. Default to the canonical execution gate; supplier_contact → HUMAN_REVIEW (SUP-04).
    if decide_fn is None:
        from src.app.policy.execution_gate import decide as decide_fn  # type: ignore[assignment]
    verdict = None
    with contextlib.suppress(Exception):
        verdict = decide_fn(
            "supplier_contact",
            value_cents=int(value_cents or 0),
            context={"kind": draft.kind, "supplier": draft.supplier_name},
            actor=actor,
            tenant_id=tenant_id,
        )
    allowed = bool(getattr(verdict, "allowed", False))
    out["verdict"] = {
        "decision": str(getattr(getattr(verdict, "decision", None), "value", "human_review")),
        "reason": str(getattr(verdict, "reason", "gate unavailable — held")),
    }
    if not allowed:
        out["status"] = "held_for_review"
        out["reason"] = "execution gate did not ALLOW supplier_contact"
        return out

    # 2) Recipient allowlist (defense in depth — never email a non-allowlisted domain).
    domain_trusted_fn = domain_trusted_fn or _default_domain_trusted
    trusted = False
    with contextlib.suppress(Exception):
        trusted = bool(domain_trusted_fn(draft.supplier_email))
    if not trusted:
        out["status"] = "blocked_recipient"
        out["reason"] = "recipient domain not on trusted-supplier allowlist"
        return out

    # 2b) Outbound INTEGRITY scan of the DRAFTED content — we must never RELAY a poisoned payload
    # (injected instructions, exfil/C2, links) or LEAK secrets to a supplier, becoming a threat
    # vector ourselves. block → do not send; review → hold for a human.
    try:
        from src.app.services.fulfillment.outbound_integrity import scan_outbound_supplier_message
        integrity = scan_outbound_supplier_message(draft.subject, draft.body, recipient=draft.supplier_email)
    except Exception:
        integrity = {"action": "allow", "findings": [], "categories": []}
    out["integrity"] = integrity
    if integrity.get("action") == "block":
        out["status"] = "blocked_content"
        out["reason"] = "drafted supplier message failed the outbound integrity scan (data leak or relayed payload)"
        return out
    if integrity.get("action") == "review":
        out["status"] = "held_for_review"
        out["reason"] = "drafted supplier message flagged by the outbound integrity scan"
        return out

    # 3) Send via the injected mailer (default NullMailer sends nothing).
    mailer = mailer or NullMailer()
    result: Dict[str, Any] = {"ok": False, "status": "not_sent"}
    with contextlib.suppress(Exception):
        result = mailer.send(
            to_email=draft.supplier_email, subject=draft.subject, body=draft.body, from_email=from_email
        ) or result
    out["send_result"] = result
    out["sent"] = bool(result.get("ok"))
    out["status"] = "sent" if out["sent"] else "send_failed"
    return out
