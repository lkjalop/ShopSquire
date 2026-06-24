"""B2B intent assessment (agnostic core) — quantity is a SIGNAL, not a deterministic gate.

A naive "quantity >= 5 → B2B" rule is wrong in both directions: a consumer can buy 5 (family/gifts)
and a business can buy 2; and an absurd quantity ("999,999 laptops") is more likely a fat-finger or a
prompt-injection probe than a real order. This assesses the BUYER'S INTENT by combining the quantity
with business-language signals, then routes:

  * consumer        — small qty, no business signal → normal consumer flow.
  * b2b             — business language present (any qty) → procurement flow; discount-eligible if bulk.
  * ambiguous_bulk  — bulk qty but NO business signal → CLARIFY (ask "is this for a business?") and
                      flag for review rather than silently assuming a bulk B2B deal.
  * anomalous       — qty above a sane ceiling → likely error / prompt attack / a deal too large to
                      auto-quote → escalate to a human; never auto-process.

Vertical-blind: "business/company/team/staff/office/fleet/procurement" is generic commerce language,
not electronics flavour. Thresholds are profile/env-overridable. Pure + never raises.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

VERDICT_CONSUMER = "consumer"
VERDICT_B2B = "b2b"
VERDICT_AMBIGUOUS_BULK = "ambiguous_bulk"
VERDICT_ANOMALOUS = "anomalous"

# Generic business-procurement language (vertical-blind). A buyer expressing ANY of these is buying
# for an organisation, not themselves — that, not the raw count, is the B2B signal.
_BUSINESS_RE = re.compile(
    r"\b(business|businesses|company|companies|corporate|enterprise|organisation|organization|"
    r"org|team|teams|staff|employees?|workforce|department|office|offices|fleet|procurement|"
    r"purchase\s+order|\bp\.?o\.?\b|invoice|tax\s+invoice|abn|vat|reseller|wholesale|bulk|"
    r"deploy(?:ment)?|roll\s?out|onboard(?:ing)?|for\s+(?:our|the)\s+(?:team|staff|office|company|firm)|"
    r"new\s+hires?|headcount|seats?)\b",
    re.IGNORECASE,
)
# Consumer-personal cues that argue AGAINST B2B even with a few units (gifts/family).
_PERSONAL_RE = re.compile(
    r"\b(for\s+(?:me|myself|my\s+(?:kid|son|daughter|wife|husband|family|partner|mum|dad|mom))|"
    r"personal|gift|present|home\s+use|for\s+my\s+home)\b",
    re.IGNORECASE,
)


def _i(env: str, default: int) -> int:
    try:
        return int(os.getenv(env, str(default)) or default)
    except (TypeError, ValueError):
        return default


@dataclass
class B2BAssessment:
    verdict: str
    quantity: int
    is_bulk: bool
    business_signal: bool
    discount_eligible: bool
    escalate: bool
    reasons: List[str] = field(default_factory=list)

    @property
    def is_b2b(self) -> bool:
        return self.verdict == VERDICT_B2B

    @property
    def wants_procurement_questions(self) -> bool:
        # Fire the B2B procurement question pack for a real B2B order OR to disambiguate a bulk order
        # whose business intent is unclear (the question itself resolves it).
        return self.verdict in (VERDICT_B2B, VERDICT_AMBIGUOUS_BULK)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "verdict": self.verdict, "quantity": self.quantity, "is_bulk": self.is_bulk,
            "business_signal": self.business_signal, "discount_eligible": self.discount_eligible,
            "escalate": self.escalate, "reasons": list(self.reasons),
        }


def assess_b2b_intent(
    query: Optional[str],
    *,
    quantity: Optional[int] = None,
    bulk_min: Optional[int] = None,
    anomaly_ceiling: Optional[int] = None,
) -> B2BAssessment:
    """Assess whether the buyer intends a business/bulk purchase. Never raises."""
    try:
        q = str(query or "")
        qty = int(quantity) if isinstance(quantity, int) and quantity > 0 else 1
        bmin = int(bulk_min) if isinstance(bulk_min, int) and bulk_min > 0 else _i("B2B_BULK_MIN", 5)
        ceiling = int(anomaly_ceiling) if isinstance(anomaly_ceiling, int) and anomaly_ceiling > 0 else _i("B2B_ANOMALY_CEILING", 1000)

        business = bool(_BUSINESS_RE.search(q)) and not bool(_PERSONAL_RE.search(q))
        is_bulk = qty >= bmin
        reasons: List[str] = []

        if qty > ceiling:
            reasons.append(f"quantity {qty} exceeds the sane ceiling ({ceiling}) — likely an error, an "
                           "attack, or a deal too large to auto-quote; routing to a human")
            return B2BAssessment(VERDICT_ANOMALOUS, qty, is_bulk, business, False, True, reasons)

        if business:
            reasons.append("business/procurement language detected")
            if is_bulk:
                reasons.append(f"bulk quantity ({qty}) → volume-discount eligible")
            return B2BAssessment(VERDICT_B2B, qty, is_bulk, True, is_bulk, False, reasons)

        if is_bulk:
            reasons.append(f"bulk quantity ({qty}) but no business signal — clarify whether this is a "
                           "business purchase before assuming a B2B deal")
            return B2BAssessment(VERDICT_AMBIGUOUS_BULK, qty, True, False, False, True, reasons)

        return B2BAssessment(VERDICT_CONSUMER, qty, False, False, False, False, ["consumer-scale purchase"])
    except Exception:
        # Fail toward a human on unexpected input rather than mis-route a purchase.
        return B2BAssessment(VERDICT_AMBIGUOUS_BULK, int(quantity or 1), False, False, False, True,
                             ["b2b intent assessment error — defaulting to review"])
