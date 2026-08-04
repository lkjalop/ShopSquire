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
    "in_house_financing": r"financ\w+|\bloan\b|credit\s*(?:terms|line|option)|lease-?to-?own",
    # audit 2026-07-08: \bleas\w+ matched "least" ("at least 16GB RAM" injected the whole
    # does-not-offer list) — enumerate real lease forms only
    "leasing": r"\bleas(?:e|es|ed|ing)\b|\brent(?:al|ing)?\b|\bhire\b",
    "trade_in": r"trade[\s-]?in|buy[\s-]?back|part[\s-]?exchange",
}

_HUMAN_LABELS: Dict[str, str] = {
    "payment_plans": "payment plans / instalment options",
    "in_house_financing": "in-house financing",
    "leasing": "leasing or rental",
    "trade_in": "trade-in or buyback",
}

# Buyer phrasings that make the fulfilment/backorder fact relevant. Audit 2026-07-08:
# "how many"/"wait"/"availab\w+" injected reorder talk into port-count and feature questions —
# require explicit stock/reorder vocabulary.
_BACKORDER_TOPIC = re.compile(
    r"back[\s-]?order|re-?order|restock|re-?stock|lead\s*time|in\s*stock|out\s*of\s*stock|"
    r"stock\s*level|wait\s*(?:for|on)\s*(?:a\s*)?(?:re-?order|restock|re-?stock|stock|delivery|units)",
    re.I,
)


def get_capabilities(profile_id: Optional[str] = None) -> Dict[str, Any]:
    """The profile's declared capability boundary; {} when the vertical declares none."""
    caps = profile_slot("capabilities", profile_id=profile_id, default={})
    return caps if isinstance(caps, dict) else {}


def _max_amount(query: str) -> float:
    """Largest MONEY amount in the query — via budget_grammar, the platform's ONE money parser
    (audit 2026-07-08: a hand-rolled regex here was the sixth duplicate grammar and read
    'i9-14900K' as $14,900,000 and '20000mAh' as $20,000, falsely triggering the autonomy note;
    budget_grammar's unit guard rejects both)."""
    try:
        from src.app.services.budget_grammar import parse_budget
        parsed = parse_budget(query)
        if parsed is None:
            return 0.0
        vals = [v for v in (getattr(parsed, "budget_min", None), getattr(parsed, "budget_max", None)) if v]
        return float(max(vals)) if vals else 0.0
    except Exception:
        return 0.0


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
            if not isinstance(spec, dict):
                continue
            if re.search(str(spec.get("pattern") or ""), q) and spec.get("statement"):
                lines.append(f"- {spec['statement']}")
        except Exception:
            # ANY malformed entry skips fail-safe (audit 2026-07-08: catching re.error only let a
            # non-dict entry raise AttributeError, and the caller's blanket except then dropped
            # the ENTIRE capability note — one bad line silently un-declared the whole boundary)
            continue

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
