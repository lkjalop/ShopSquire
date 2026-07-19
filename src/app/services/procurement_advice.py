"""Procurement advice and continuity shared by legacy and V2 recommendation paths.

This module never creates a case, drafts a message, or contacts a supplier. Consequential work
stays in the fulfillment domain/router; recommendation paths may only explain and preserve intent.
"""
from __future__ import annotations

from typing import Any, Dict, Optional


def sourcing_continuity(last_sourcing_intent: Any) -> Optional[Dict[str, Any]]:
    intent = last_sourcing_intent if isinstance(last_sourcing_intent, dict) else {}
    lines = [line for line in (intent.get("lines") or []) if isinstance(line, dict)]
    normalized = []
    for line in lines[:6]:
        item_ref = str(line.get("item_ref") or "").strip()
        try:
            quantity = max(0, int(line.get("quantity") or 0))
        except (TypeError, ValueError):
            quantity = 0
        if item_ref and quantity:
            normalized.append({"item_ref": item_ref, "quantity": quantity})
    if not normalized:
        return None
    units = sum(line["quantity"] for line in normalized)
    items = ", ".join(f"{line['quantity']}x {line['item_ref']}" for line in normalized)
    return {
        "units": units,
        "lines": normalized,
        "confirmed": False,
        "memo": (
            f"The buyer previously previewed a sourcing request ({units} units: {items}) that is not "
            "yet confirmed. If this turn refers to it ('cheaper', 'change it', 'that order'), continue "
            "from that request."
        ),
    }


def append_sourcing_continuity(history: str, last_sourcing_intent: Any) -> str:
    continuity = sourcing_continuity(last_sourcing_intent)
    if not continuity:
        return str(history or "")
    return f"{history}\n{continuity['memo']}".strip() if history else continuity["memo"]


def resolve_active_request_id(*, mem: Any, uid: str, uid_hash: Optional[str], trace_id: Optional[str],
                              tenant_id: str, now_iso: str) -> Optional[str]:
    """Keep amendments on one stable PR. Persistence is session continuity, not case execution."""
    from src.app.services.fulfillment import procurement_request
    kv = mem.get_kv(uid) or {}
    active = procurement_request.resolve_pr(
        kv.get("active_pr"), tenant_id=str(tenant_id or "default"),
        buyer_key=str(uid_hash or uid or "anon"), now_iso=now_iso,
        nonce=str(trace_id or now_iso),
    )
    kv["active_pr"] = active
    mem.set_kv(uid, kv)
    return active.get("pr_id")
