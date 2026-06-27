"""OKF (Open Knowledge Format) export for a procurement case — a portable, vendor-neutral
"why-the-agent-decided-this" artifact (markdown + YAML frontmatter, per Google Cloud OKF v0.1).

The bundle is a single ``type: ProcurementCase`` document: buyer requirement, the approved-supplier RFQ
(recipient + content hash + evidence packet + pre-send gate), any RFI clarification, the validated quote /
PO, and the full bitemporal decision journey. Any AI agent or auditor can read it without an SDK.

Agnostic CORE: reads the OPAQUE case state + journey only — no vertical vocabulary. The supplier draft body
is already claim-safe (no price/PO leak), so it is safe to include in the audit artifact. Never raises.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


def _scalar(v: Any) -> str:
    """A YAML-scalar-safe one-line rendering for frontmatter values."""
    return str(v if v is not None else "").replace("\n", " ").replace('"', "'").strip()


def _frontmatter(fields: Dict[str, Any]) -> str:
    lines = ["---"]
    for k, v in fields.items():
        if isinstance(v, list):
            lines.append(f"{k}: [{', '.join(_scalar(x) for x in v if str(x).strip())}]")
        else:
            lines.append(f"{k}: {_scalar(v)}")
    lines.append("---")
    return "\n".join(lines)


def case_to_okf(*, case_id: str, state: str, state_json: Optional[Dict[str, Any]] = None,
                journey: Optional[List[Dict[str, Any]]] = None, timestamp: str = "") -> str:
    """Render one procurement case as an OKF v0.1 document (markdown + YAML frontmatter)."""
    sj = state_json or {}
    avail = sj.get("availability") if isinstance(sj.get("availability"), dict) else {}
    reqs = sj.get("requirements") if isinstance(sj.get("requirements"), dict) else {}
    draft = sj.get("draft") if isinstance(sj.get("draft"), dict) else {}
    rfi = sj.get("rfi") if isinstance(sj.get("rfi"), dict) else {}
    rfi_resp = sj.get("rfi_response") if isinstance(sj.get("rfi_response"), dict) else {}
    pq = sj.get("validated_quote") or sj.get("parsed_quote") or {}
    po = sj.get("purchase_order") if isinstance(sj.get("purchase_order"), dict) else {}
    item_ref = str(avail.get("item_ref") or (draft.get("commercial_scope") or {}).get("item_ref") or "")
    short8 = str(case_id)[:8]

    tags = ["procurement", str(state).lower()] + ([item_ref] if item_ref else [])
    fm = _frontmatter({
        "type": "ProcurementCase",
        "title": f"Procurement case {short8} - {state}",
        "description": (f"Bounded-autonomy procurement for {item_ref or 'an item'}; shortfall "
                        f"{avail.get('shortfall', '?')} of {avail.get('requested_qty', '?')}; state {state}."),
        "resource": f"/api/v1/fulfillment/cases/{case_id}",
        "tags": tags,
        "timestamp": timestamp,
    })

    out: List[str] = [fm, "", f"# Procurement case {short8}", "", f"**State:** {state}", ""]

    out += ["## Buyer requirement",
            f"- Item: `{item_ref or 'unknown'}` - requested {avail.get('requested_qty', '?')} - "
            f"in stock {avail.get('in_stock', '?')} - shortfall {avail.get('shortfall', '?')}"]
    if reqs.get("use_case"):
        out += [f"- Intended use: {reqs.get('use_case')}"]
    if isinstance(reqs.get("specs"), list) and reqs.get("specs"):
        out += [f"- Required specs: {', '.join(str(s) for s in reqs['specs'][:6])}"]
    if reqs.get("needed_within_days"):
        out += [f"- Needed within: {reqs.get('needed_within_days')} days"]
    out += [""]

    if draft.get("subject"):
        gate = (draft.get("send_gate") or {}).get("decision")
        out += ["## Supplier RFQ (draft)",
                f"- Recipient: {draft.get('recipient_email') or draft.get('recipient_domain') or 'unresolved'} "
                f"(domain `{draft.get('recipient_domain') or 'unknown'}`, resolved from the approved allowlist)",
                f"- Content hash: `{str(draft.get('content_hash') or '')[:16]}`",
                f"- Pre-send gate: {gate or 'n/a'}",
                "",
                f"**Subject:** {draft.get('subject')}",
                "",
                "```text", str(draft.get("body") or ""), "```", ""]
        ev = draft.get("evidence") if isinstance(draft.get("evidence"), list) else []
        if ev:
            out += ["### Evidence packet"]
            for e in ev:
                out += [f"- `{e.get('evidence_id') or e.get('source')}` {e.get('source')}: {e.get('summary')}"]
            out += [""]

    if rfi.get("question"):
        out += ["## Supplier clarification (RFI)",
                f"- Question: {rfi.get('question')}",
                f"- Sent to: {rfi.get('recipient') or rfi.get('recipient_domain')} - ref `{rfi.get('provider_ref') or ''}`"]
        if rfi_resp.get("answer"):
            out += [f"- Supplier reply: {rfi_resp.get('answer')}"]
        out += [""]

    if isinstance(pq, dict) and pq.get("quoted_quantity") is not None:
        out += ["## Supplier quote (validated)",
                f"- Qty {pq.get('quoted_quantity')} - dispatch {pq.get('dispatch_ready_at')} - "
                f"expires {pq.get('quote_expires_at')} - confidence {pq.get('confidence')}", ""]
    if po.get("status"):
        out += ["## Purchase order",
                f"- {po.get('po_ref') or 'proposed'} - status {po.get('status')} - qty {po.get('quantity')}", ""]

    if journey:
        out += ["## Decision journey (bitemporal)"]
        for i, e in enumerate(journey, 1):
            rc = f" ({e.get('reason_code')})" if e.get("reason_code") else ""
            out += [f"{i}. `{e.get('event')}` -> **{e.get('state')}** by {e.get('actor_type')}{rc} - {e.get('valid_from')}"]
        out += [""]

    return "\n".join(out)
