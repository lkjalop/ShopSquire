"""Budget gate (agnostic CORE) — the enterprise 'is there budget for this spend' check.

Classic P2P blocks/escalates a purchase that would breach the requesting category's budget. This computes,
for a case's spend, whether it fits the category's remaining budget. Caps are DATA from the StoreProfile
(category_budget_caps + default_budget_cap_cents) — core stays vertical-blind: it does cents arithmetic
against a cap keyed by an opaque category label.

``committed_cents`` (spend already committed this period for the category) is supplied by the caller, so the
policy is pure + testable; a cap of None means 'no budget limit configured' → always within budget.
Enforcement is OPT-IN (FULFILLMENT_BUDGET_GATE_ENABLED): default-off surfaces the status only; on, an
over-budget purchase is blocked/escalated at the send gate.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger("shopsquire.budget_gate")


def _profile(slot: str, default: Any) -> Any:
    try:
        from src.app.platform.store_profile import profile_slot
        v = profile_slot(slot, default=None)
        return v if v is not None else default
    except Exception:
        return default


def _cap_for(category: str) -> Optional[int]:
    """The budget cap (cents) for a category: the per-category map first, else the default cap, else None
    (no limit). StoreProfile slots: category_budget_caps {category: cents}, default_budget_cap_cents."""
    caps = _profile("category_budget_caps", None) or {}
    if isinstance(caps, dict):
        key = str(category or "").strip().lower()
        if key and key in {str(k).strip().lower(): k for k in caps}:
            try:
                return int(caps[{str(k).strip().lower(): k for k in caps}[key]])
            except (TypeError, ValueError):
                return None
    dflt = _profile("default_budget_cap_cents", None)
    try:
        return int(dflt) if dflt is not None else None
    except (TypeError, ValueError):
        return None


def budget_status(spend_cents: Any, *, category: str = "default", committed_cents: Any = 0) -> Dict[str, Any]:
    """Whether a spend fits the category's remaining budget. Returns
    {within_budget, cap_cents, committed_cents, spend_cents, remaining_cents, category, reason}. A cap of
    None = no limit configured → within_budget True. Pure; never raises."""
    try:
        spend = max(0, int(spend_cents or 0))
    except (TypeError, ValueError):
        spend = 0
    try:
        committed = max(0, int(committed_cents or 0))
    except (TypeError, ValueError):
        committed = 0
    cap = _cap_for(category)
    if cap is None:
        return {"within_budget": True, "cap_cents": None, "committed_cents": committed, "spend_cents": spend,
                "remaining_cents": None, "category": category, "reason": "no_budget_cap_configured"}
    remaining_before = cap - committed
    within = (committed + spend) <= cap
    return {"within_budget": within, "cap_cents": cap, "committed_cents": committed, "spend_cents": spend,
            "remaining_cents": max(0, remaining_before), "category": category,
            "reason": ("ok" if within else
                       f"spend {spend/100:.0f} exceeds remaining {max(0, remaining_before)/100:.0f} "
                       f"of the {category} budget {cap/100:.0f}")}
