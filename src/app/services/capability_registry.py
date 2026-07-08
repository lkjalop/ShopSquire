"""Capability registry — the store's honest "what we do NOT do" (agnostic core).

Why this exists (proven live, model A/B rounds 3-4, 2026-07-08): every candidate model
(qwen3/gemma3/phi4/granite4) fabricated payment-plan availability when asked "do you offer
payment plans?", because the platform never handed any model the fact that the store doesn't.
A narrator cannot be honest about a fact it was never given. The fix is declarative: the store
profile states its capability boundary ONCE (`capabilities` slot) and this module turns the
relevant part of it into a short authoritative preamble note the narrator must ground on —
for INFINITE phrasings, with zero per-phrasing hand-coding in recommend.py.

Demarcation: this module is pure DATA→NOTE assembly (deterministic, <1ms, no LLM). The nuance
of *saying* it kindly is the narrator's job; the truth of WHAT is said comes from here.

Agnostic-core contract: the universal topic vocabulary below covers commerce-universal concepts
only (payment plans / financing / leasing / trade-in / order-size / backorder). Vertical-specific
capabilities go in the profile's `capabilities.custom` slot (pattern + statement), never here.
A profile with no `capabilities` slot emits no note — silence, not invented policy.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from src.app.platform.store_profile import profile_slot

# Commerce-universal offerings a buyer may ask about. Slug -> detection regex (matched against
# the buyer's raw query, lowercase). A slug only ever produces a statement when the PROFILE
# declares it under does_not_offer — detection alone never asserts anything.
_UNIVERSAL_TOPICS: Dict[str, str] = {
    "payment_plans": r"payment\s*plan|pay\s*(?:monthly|weekly|later|in\s*insta)|installment|instalment|afterpay|zip\s*pay|klarna|layby|lay-?away",
    "in_house_financing": r"financ\w+|loan|credit\s*(?:terms|line|option)|lease-?to-?own",
    "leasing": r"\bleas\w+|\brent\w*\b|\bhire\b",
    "trade_in": r"trade[\s-]?in|buy[\s-]?back|part[\s-]?exchange",
}

_HUMAN_LABELS: Dict[str, str] = {
    "payment_plans": "payment plans / instalment options",
    "in_house_financing": "in-house financing",
    "leasing": "leasing or rental",
    "trade_in": "trade-in or buyback",
}

# Buyer phrasings that make the fulfilment/backorder fact relevant.
_BACKORDER_TOPIC = re.compile(
    r"back[\s-]?order|re-?order|restock|re-?stock|lead\s*time|in\s*stock|out\s*of\s*stock|availab\w+|how\s*many|wait\w*", re.I
)

# Money amounts for the autonomy-limit fact: "$25,000", "25000", "$25k", "25 k".
_MONEY = re.compile(r"\$?\s*(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s*(k\b)?", re.I)


def get_capabilities(profile_id: Optional[str] = None) -> Dict[str, Any]:
    """The profile's declared capability boundary; {} when the vertical declares none."""
    caps = profile_slot("capabilities", profile_id=profile_id, default={})
    return caps if isinstance(caps, dict) else {}


def _max_amount(query: str) -> float:
    best = 0.0
    for m in _MONEY.finditer(query):
        try:
            val = float(m.group(1).replace(",", ""))
        except Exception:
            continue
        if m.group(2):
            val *= 1000
        best = max(best, val)
    return best


def capability_preamble_note(query: str, profile_id: Optional[str] = None) -> Optional[str]:
    """Authoritative store-capability facts relevant to THIS query, or None.

    Emits at most a few lines so the narration preamble stays small: the does_not_offer line
    only when the query touches a declared-absent offering; the autonomy line only when a
    mentioned amount reaches the limit; the backorder line only on availability phrasings.
    """
    caps = get_capabilities(profile_id)
    if not caps or not (query or "").strip():
        return None
    q = query.lower()
    lines: List[str] = []

    declared = [s for s in (caps.get("does_not_offer") or []) if isinstance(s, str)]
    custom = caps.get("custom") if isinstance(caps.get("custom"), dict) else {}
    topic_hit = any(
        slug in _UNIVERSAL_TOPICS and re.search(_UNIVERSAL_TOPICS[slug], q) for slug in declared
    )
    if topic_hit and declared:
        labels = ", ".join(_HUMAN_LABELS.get(s, s.replace("_", " ")) for s in declared)
        offered = [str(x) for x in (caps.get("payment_methods") or []) if x]
        line = f"- This store does NOT offer: {labels}. State this plainly; do not suggest third-party retailers or invent alternatives."
        if offered:
            line += f" Accepted payment: {', '.join(offered)}."
        lines.append(line)
    for slug, spec in (custom or {}).items():
        try:
            if re.search(str(spec.get("pattern") or ""), q) and spec.get("statement"):
                lines.append(f"- {spec['statement']}")
        except re.error:
            continue  # malformed vertical pattern: skip fail-safe, never crash narration

    limits = caps.get("autonomy_limits") if isinstance(caps.get("autonomy_limits"), dict) else {}
    try:
        limit = float(limits.get("max_autonomous_order_value_usd") or 0)
    except Exception:
        limit = 0.0
    if limit and _max_amount(q) >= limit:
        lines.append(
            f"- Orders at or above ${limit:,.0f} require a human account manager: offer to bring one into this conversation rather than finalizing alone."
        )

    ful = caps.get("fulfilment") if isinstance(caps.get("fulfilment"), dict) else {}
    if ful.get("backorder") and _BACKORDER_TOPIC.search(q):
        days = ful.get("typical_reorder_days")
        eta = f" (typically ~{int(days)} days)" if isinstance(days, (int, float)) and days else ""
        lines.append(
            f"- Quantity shortfalls CAN be backordered via supplier reorder{eta}, but only with the buyer's explicit consent — ask before assuming."
        )

    if not lines:
        return None
    return "STORE CAPABILITY FACTS (authoritative — answer honestly from these; never invent offerings):\n" + "\n".join(lines)
