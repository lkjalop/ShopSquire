"""Approval-tier policy (agnostic CORE) — the enterprise 'who must approve this spend' gate.

Classic P2P routes a purchase to a HIGHER approver as the value rises (auto → manager → director →
executive). This module computes the required approval tier for a case's spend, so the decision is recorded
in the trace and (flag-gated) enforced at the human send gate. The dollar tiers are DATA from the
StoreProfile (approval_value_tiers) — core stays vertical-blind: it compares cents to thresholds, nothing else.

Enforcement is OPT-IN (FULFILLMENT_APPROVAL_TIERS_ENABLED): default-off preserves the single-gate behaviour;
on, an approver below the required level is rejected so the case escalates to the right authority.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("shopsquire.approval_policy")

# Default spend→tier ladder (CENTS). Governance vocabulary (tier names + dollar bands), not product flavour;
# the active StoreProfile overrides via the approval_value_tiers slot. max_cents=None = the top (no ceiling).
_DEFAULT_TIERS: List[Dict[str, Any]] = [
    {"max_cents": 100000, "tier": "auto", "min_level": 1},        # ≤ $1,000  — line-level / auto-eligible
    {"max_cents": 1000000, "tier": "manager", "min_level": 2},    # ≤ $10,000 — manager
    {"max_cents": 10000000, "tier": "director", "min_level": 3},  # ≤ $100,000 — director
    {"max_cents": None, "tier": "executive", "min_level": 4},     # > $100,000 — executive / finance
]

# Default role→approval-level map. The StoreProfile (approval_role_levels) overrides; an unknown role = 0
# (cannot clear any non-auto tier). Owner is the highest standing approver.
_DEFAULT_ROLE_LEVELS: Dict[str, int] = {"owner": 4, "admin": 4, "director": 3, "manager": 2, "merchant": 2}


def _profile(slot: str, default: Any) -> Any:
    try:
        from src.app.platform.store_profile import profile_slot
        v = profile_slot(slot, default=None)
        return v if v is not None else default
    except Exception:
        return default


def required_approval_tier(value_cents: Any, *, tiers: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """The required approval tier for a spend of ``value_cents``. Returns
    {tier, min_level, value_cents, reason}. First band whose max_cents covers the value wins; the final
    (max_cents=None) band is the catch-all top tier. Invalid spend is rejected."""
    if type(value_cents) is not int or value_cents < 0:
        raise ValueError('spend_must_be_nonnegative_integer_cents')
    v = value_cents
    bands = tiers if tiers is not None else _profile("approval_value_tiers", _DEFAULT_TIERS)
    _validate_tiers(bands)
    for band in bands:
        mc = band.get("max_cents")
        if mc is None or v <= int(mc):
            return {"tier": str(band.get("tier") or "review"), "min_level": int(band.get("min_level") or 1),
                    "value_cents": v, "reason": f"spend {v/100:.0f} → {band.get('tier')} tier"}
    last = bands[-1] if bands else {"tier": "executive", "min_level": 4}
    return {"tier": str(last.get("tier") or "executive"), "min_level": int(last.get("min_level") or 4),
            "value_cents": v, "reason": "spend above all bands → top tier"}


def _validate_tiers(bands):
    if not isinstance(bands,list) or not bands:
        raise ValueError('invalid_approval_tiers')
    previous_cap,previous_level=-1,0
    for index,band in enumerate(bands):
        if not isinstance(band,dict):raise ValueError('invalid_approval_tiers')
        cap,level=band.get('max_cents'),band.get('min_level')
        if (not isinstance(band.get('tier'),str) or not band['tier'].strip()
                or type(level) is not int or level<1 or level<previous_level):
            raise ValueError('invalid_approval_tiers')
        if index==len(bands)-1:
            if cap is not None:raise ValueError('invalid_approval_tiers')
        elif type(cap) is not int or cap<=previous_cap:
            raise ValueError('invalid_approval_tiers')
        previous_cap,previous_level=cap,level


def approver_level(role: str) -> int:
    """The approval LEVEL of an actor role (StoreProfile approval_role_levels, else the default map).
    Unknown role → 0 (clears only the 'auto' tier)."""
    levels = _profile("approval_role_levels", _DEFAULT_ROLE_LEVELS)
    if not isinstance(levels,dict) or any(not isinstance(role,str) or not role.strip()
            or type(level) is not int or level<0 for role,level in levels.items()):
        raise ValueError('invalid_approval_role_levels')
    return int(levels.get(str(role or "").strip().lower(), 0))


def approver_can_clear(role: str, value_cents: Any) -> Dict[str, Any]:
    """Whether ``role`` may approve a spend of ``value_cents``. Returns
    {ok, required_tier, required_level, approver_level, reason}. Pure."""
    req = required_approval_tier(value_cents)
    lvl = approver_level(role)
    ok = lvl >= int(req["min_level"])
    return {"ok": ok, "required_tier": req["tier"], "required_level": req["min_level"],
            "approver_level": lvl, "value_cents": req["value_cents"],
            "reason": ("ok" if ok else f"{role or 'actor'} (level {lvl}) below required {req['tier']} "
                                       f"(level {req['min_level']}) for spend {req['value_cents']/100:.0f}")}
