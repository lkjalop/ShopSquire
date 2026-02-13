from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

from src.app.feature_flags import get_flags


def _get_trust_thresholds() -> Dict[str, float]:
    thr: Dict[str, float] = {}
    try:
        flags = get_flags()
        raw = flags.get("TRUST_THRESHOLDS", {}) if isinstance(flags.get("TRUST_THRESHOLDS"), dict) else {}
    except Exception:
        raw = {}

    def _f(key: str, default: float) -> float:
        try:
            return float(raw.get(key, default))
        except Exception:
            return default

    thr["high_trust_min"] = _f("high_trust_min", 0.8)
    thr["medium_trust_min"] = _f("medium_trust_min", 0.6)
    thr["guarded_trust_min"] = _f("guarded_trust_min", 0.4)
    thr["supervisor_review_amount_usd_min"] = _f("supervisor_review_amount_usd_min", 500.0)
    return thr


def compute_trust_score(history: Dict) -> float:
    """Compute a lightweight trust score from customer history signals."""
    score = 0.5
    if history.get("account_age_days", 0) > 365:
        score += 0.1
    if history.get("loyalty_tier") in ("gold", "platinum"):
        score += 0.15
    if history.get("total_orders", 0) > 10:
        score += 0.1
    if history.get("email_verified") and history.get("phone_verified"):
        score += 0.05
    if history.get("return_rate", 0.0) > 0.3:
        score -= 0.2
    if history.get("fraud_flags", 0) > 0:
        score -= 0.3
    if history.get("returns_last_30_days", 0) > 3:
        score -= 0.15
    return max(0.0, min(1.0, score))


def auto_approve_thresholds(trust_score: float) -> Dict[str, float]:
    """Return auto-approve thresholds based on trust score tiers."""
    thr = {}
    try:
        flags = get_flags()
        thr = flags.get("TRUST_THRESHOLDS", {}) if isinstance(flags.get("TRUST_THRESHOLDS"), dict) else {}
    except Exception:
        thr = {}

    def _f(key: str, default: float) -> float:
        try:
            return float(thr.get(key, default))
        except Exception:
            return default

    high_min = _f("high_trust_min", 0.8)
    med_min = _f("medium_trust_min", 0.6)
    guarded_min = _f("guarded_trust_min", 0.4)
    max_high = _f("max_amount_usd_high", 500.0)
    max_med = _f("max_amount_usd_medium", 200.0)
    max_guarded = _f("max_amount_usd_guarded", 50.0)
    max_low = _f("max_amount_usd_low", 0.0)

    if trust_score >= high_min:
        return {"max_amount_usd": max_high}
    if trust_score >= med_min:
        return {"max_amount_usd": max_med}
    if trust_score >= guarded_min:
        return {"max_amount_usd": max_guarded}
    return {"max_amount_usd": max_low}


@dataclass
class TrustRoutingDecision:
    route: str
    trust_score: float
    tier: str
    reasons: List[str]


def route_from_trust(
    *,
    trust_score: float,
    risk_band: str | None = None,
    amount_usd: float | None = None,
) -> TrustRoutingDecision:
    """Route a case based on trust + risk + amount.

    Returns a decision that downstream CV/support flows can use.
    """
    thr = _get_trust_thresholds()
    reasons: List[str] = []
    tier = "low"
    if trust_score >= thr["high_trust_min"]:
        tier = "high"
    elif trust_score >= thr["medium_trust_min"]:
        tier = "medium"
    elif trust_score >= thr["guarded_trust_min"]:
        tier = "guarded"

    route = "standard_queue"
    if risk_band in ("high", "critical"):
        route = "security_review"
        reasons.append("risk_band_high")
    if amount_usd is not None:
        if amount_usd >= thr["supervisor_review_amount_usd_min"]:
            reasons.append("high_amount")
            route = "supervisor_review"
    if tier == "high" and route == "standard_queue":
        route = "auto_process"
        reasons.append("high_trust")
    if tier in ("low", "guarded") and route == "standard_queue":
        reasons.append("low_trust")

    return TrustRoutingDecision(route=route, trust_score=trust_score, tier=tier, reasons=reasons)
