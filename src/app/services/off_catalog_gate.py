"""Off-catalog capability gate (W3, 2026-07-08) — the "$80k A100 servers → gaming laptops"
fix, live-observed in both independent audits. When the buyer asks for a HARDWARE CLASS the
store does not sell (rack-mount servers, datacenter GPUs), pattern-matching tokens like "GPU"
into the laptop catalog produces a confident wrong sale. The honest answer is: say we don't
stock the category, offer the EXISTING supplier-RFQ machinery (rfq_fanout / procurement cases),
and escalate to a human when the stated spend crosses the autonomy limit.

Agnostic core: the class patterns live in the store profile (capabilities.off_catalog_classes)
— a pharmacy declares different non-sold classes than an electronics store. No profile slot ->
gate never fires. Never raises."""
from __future__ import annotations

import re
from typing import Any, Dict, Optional

from src.app.platform.store_profile import profile_slot


def off_catalog_check(query: str, profile_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Return {"class": slug, "label": str} when the query targets a declared non-sold hardware
    class, else None."""
    q = (query or "").lower()
    if not q.strip():
        return None
    try:
        caps = profile_slot("capabilities", profile_id=profile_id, default={}) or {}
        classes = caps.get("off_catalog_classes") or []
        for entry in classes:
            if not isinstance(entry, dict):
                continue
            try:
                if re.search(str(entry.get("pattern") or ""), q):
                    return {"class": str(entry.get("class") or "off_catalog"),
                            "label": str(entry.get("label") or entry.get("class") or "this category")}
            except re.error:
                continue
    except Exception:
        return None
    return None


def off_catalog_message(hit: Dict[str, Any], query: str, profile_id: Optional[str] = None) -> str:
    """Honest, action-forward copy: category truth + supplier-ask offer + autonomy escalation
    when the stated spend reaches the limit. Grounded on the capability registry — the same
    declared facts the narrator uses, so deterministic and prose lanes agree."""
    label = hit.get("label") or "this category"
    parts = [
        f"Honest answer: we don't stock {label} in our catalog, and I won't pretend a laptop is a substitute.",
        "What I CAN do: send a request-for-quote to our suppliers for exactly what you described — "
        "you review the draft before anything is sent, and nothing is ordered without your confirmation.",
    ]
    try:
        from src.app.services.capability_registry import get_capabilities, _max_amount
        caps = get_capabilities(profile_id)
        limit = float((caps.get("autonomy_limits") or {}).get("max_autonomous_order_value_usd") or 0)
        amount = _max_amount((query or "").lower())
        if limit and amount >= limit:
            parts.append(
                f"Since this is a ${amount:,.0f} request (above our ${limit:,.0f} threshold), "
                "I'll also bring a human account manager into the loop before anything is finalized."
            )
    except Exception:
        pass
    return " ".join(parts)
