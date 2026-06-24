"""Escalation policy — the deterministic complexity/risk metric → human-in-the-loop decision.

ONE bounded, vertical-blind function combines the signals the platform already produces into a single
escalation decision, computed in microseconds (no LLM, no added latency):

  * 1 - decomposition_confidence   — the agent isn't sure what was asked        (query_decomposer)
  * irreversible_action            — cart / payment / supplier-send             (action_authority_matrix)
  * order_quantity × order_value   — bulk / B2B exposure                        (availability_agent inputs)
  * fraud_score                    — 26+ fraud signals                          (fraud_scorer)
  * constraint_conflict            — no exact match / hard-filter would revert   (_apply_query_plan_filters)
  * claim_guard_rejected           — narration tried to hallucinate             (product_claim_guard)

The doctrine: bounded agents handle everything below threshold; crossing the threshold is the HONEST
stopgap — "we don't yet trust the bounded agent on this combination, so a human decides." It degrades
gracefully (a human reviews) instead of failing silently. As the agents get smarter the thresholds
rise; nothing here is vertical-specific.

Pure + defensive: never raises, no I/O. Thresholds are env-overridable for tuning per deployment.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# Soft-score weights (sum ~1.0). Fraud dominates; uncertainty and the two honesty signals matter most
# after it. Bulk/irreversibility are smaller on their own but combine into HARD overrides below.
_WEIGHTS = {
    "fraud": 0.30,
    "uncertainty": 0.20,
    "constraint_conflict": 0.15,
    "claim_guard_rejected": 0.15,
    "bulk_exposure": 0.10,
    "irreversibility": 0.10,
}

BAND_AUTO = "auto"               # below threshold: bounded agent proceeds
BAND_REVIEW = "review"           # soft: flag for asynchronous human review, agent may still draft
BAND_HUMAN = "human_required"    # hard: human decides before anything consequential happens


def _f(env: str, default: float) -> float:
    try:
        return float(os.getenv(env, str(default)) or default)
    except (TypeError, ValueError):
        return default


@dataclass
class EscalationDecision:
    escalate: bool
    band: str
    score: float
    reasons: List[str] = field(default_factory=list)
    factors: Dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "escalate": self.escalate, "band": self.band, "score": self.score,
            "reasons": list(self.reasons), "factors": dict(self.factors),
        }


def assess_escalation(
    *,
    decomposition_confidence: float = 1.0,
    irreversible_action: bool = False,
    order_quantity: int = 1,
    order_value_cents: int = 0,
    fraud_score: float = 0.0,
    constraint_conflict: bool = False,
    claim_guard_rejected: bool = False,
    b2b: bool = False,
    thresholds: Optional[Dict[str, float]] = None,
) -> EscalationDecision:
    """Combine the risk signals into a bounded escalation decision. Never raises."""
    try:
        t = thresholds or {}
        review_at = float(t.get("review", _f("ESCALATION_REVIEW_AT", 0.35)))
        human_at = float(t.get("human", _f("ESCALATION_HUMAN_AT", 0.60)))
        fraud_hard = float(t.get("fraud_hard", _f("ESCALATION_FRAUD_HARD", 0.70)))
        bulk_qty = int(t.get("bulk_qty", _f("ESCALATION_BULK_QTY", 5)))
        bulk_value = int(t.get("bulk_value_cents", _f("ESCALATION_BULK_VALUE_CENTS", 500000)))  # $5,000

        conf = max(0.0, min(1.0, float(decomposition_confidence if decomposition_confidence is not None else 1.0)))
        fraud = max(0.0, min(1.0, float(fraud_score or 0.0)))
        qty = int(order_quantity or 1)
        value = int(order_value_cents or 0)
        is_bulk = qty >= bulk_qty or value >= bulk_value
        bulk_exposure = min(1.0, max(qty / max(bulk_qty * 2, 1), value / max(bulk_value * 2, 1)))

        factors = {
            "fraud": fraud,
            "uncertainty": 1.0 - conf,
            "constraint_conflict": 1.0 if constraint_conflict else 0.0,
            "claim_guard_rejected": 1.0 if claim_guard_rejected else 0.0,
            "bulk_exposure": bulk_exposure,
            "irreversibility": 1.0 if irreversible_action else 0.0,
        }
        score = round(sum(_WEIGHTS[k] * v for k, v in factors.items()), 4)

        # HARD reasons force a human regardless of the soft score.
        hard_reasons: List[str] = []
        if fraud >= fraud_hard:
            hard_reasons.append("fraud signals above hard threshold")
        if irreversible_action and is_bulk:
            hard_reasons.append("irreversible action on a bulk/high-value order")
        if b2b and fraud >= (fraud_hard / 2):
            hard_reasons.append("B2B order with elevated fraud signals")
        # REVIEW reasons escalate to (at least) asynchronous human review.
        review_reasons: List[str] = []
        if constraint_conflict and (value >= bulk_value or is_bulk):
            review_reasons.append("no exact match on a high-value/bulk request")
        if conf < 0.34 and irreversible_action:
            review_reasons.append("low intent-parse confidence on an irreversible action")
        if claim_guard_rejected:
            review_reasons.append("narration was rejected as ungrounded")
        if 0 < fraud < fraud_hard:
            review_reasons.append("fraud signals present")

        if hard_reasons or score >= human_at:
            band = BAND_HUMAN
        elif review_reasons or score >= review_at:
            band = BAND_REVIEW
        else:
            band = BAND_AUTO
        reasons = hard_reasons + review_reasons
        if band != BAND_AUTO and not reasons:
            reasons.append("aggregate risk score above review threshold")
        return EscalationDecision(
            escalate=(band != BAND_AUTO), band=band, score=score, reasons=reasons[:8], factors=factors,
        )
    except Exception:
        # Fail SAFE: on any unexpected input, ask for a human rather than silently auto-proceeding.
        return EscalationDecision(escalate=True, band=BAND_REVIEW, score=1.0,
                                  reasons=["escalation policy error — defaulting to human review"], factors={})
