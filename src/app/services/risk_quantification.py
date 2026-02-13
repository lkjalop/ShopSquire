from __future__ import annotations

from typing import Any, Dict


RISK_WEIGHTS = {
    "security": 0.35,
    "cv": 0.25,
    "fraud": 0.25,
    "history": 0.15,
}

IMPACT_WEIGHTS = {
    "monetary": 0.5,
    "policy": 0.3,
    "data": 0.2,
}


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


def _map_fraud_level(level: str | None) -> float:
    levels = {
        "minimal": 0.1,
        "low": 0.25,
        "medium": 0.6,
        "high": 0.85,
    }
    return levels.get((level or "").lower(), 0.2)


def _map_cv_severity(sev: str | None) -> float:
    levels = {
        "minor": 0.2,
        "moderate": 0.45,
        "major": 0.7,
        "high": 0.8,
        "critical": 0.9,
    }
    return levels.get((sev or "").lower(), 0.3)


def _policy_impact(policy_gates: Any) -> float:
    if isinstance(policy_gates, dict):
        # If any gate indicates failure or high severity, raise impact
        for val in policy_gates.values():
            if isinstance(val, dict) and val.get("result") in ("fail", "blocked"):
                return 0.8
            if val is False:
                return 0.7
    if isinstance(policy_gates, list):
        for item in policy_gates:
            if isinstance(item, dict) and item.get("result") in ("fail", "blocked"):
                return 0.8
    return 0.3


def quantify(
    *,
    security: Dict[str, Any] | None = None,
    cv_analysis: Dict[str, Any] | None = None,
    fraud: Dict[str, Any] | None = None,
    policy_gates: Any | None = None,
    monetary_exposure: float | None = None,
    history_score: float | None = None,
) -> Dict[str, Any]:
    """Deterministic CRQ v1.

    Returns likelihood/impact (0-1), risk_score (0-100), band, and inputs/weights.
    """
    security = security or {}
    cv_analysis = cv_analysis or {}
    fraud = fraud or {}

    sec_risk = 0.0
    try:
        sec_risk = float(security.get("risk_adj") or 0.0) / 100.0
    except Exception:
        sec_risk = 0.0
    sec_risk = _clamp(sec_risk)

    cv_risk = _map_cv_severity(cv_analysis.get("severity"))
    try:
        conf = float(cv_analysis.get("confidence"))
        if conf < 0.5:
            cv_risk = _clamp(cv_risk + 0.2)
    except Exception:
        pass

    fraud_risk = _map_fraud_level(fraud.get("level"))
    try:
        score = float(fraud.get("score"))
        fraud_risk = _clamp(max(fraud_risk, score / 100.0))
    except Exception:
        pass

    hist_risk = _clamp(float(history_score)) if isinstance(history_score, (int, float)) else 0.2

    likelihood = (
        RISK_WEIGHTS["security"] * sec_risk
        + RISK_WEIGHTS["cv"] * cv_risk
        + RISK_WEIGHTS["fraud"] * fraud_risk
        + RISK_WEIGHTS["history"] * hist_risk
    )
    likelihood = _clamp(likelihood)

    monetary = 0.0
    if isinstance(monetary_exposure, (int, float)):
        monetary = _clamp(float(monetary_exposure) / 2000.0)
    policy_impact = _policy_impact(policy_gates)
    data_impact = 0.3 if security.get("signals") else 0.2
    impact = (
        IMPACT_WEIGHTS["monetary"] * monetary
        + IMPACT_WEIGHTS["policy"] * policy_impact
        + IMPACT_WEIGHTS["data"] * data_impact
    )
    impact = _clamp(impact)

    risk_score = round(likelihood * impact * 100.0, 2)
    if risk_score >= 60:
        band = "high"
    elif risk_score >= 30:
        band = "medium"
    else:
        band = "low"

    return {
        "model": "crq_v1",
        "likelihood": round(likelihood, 3),
        "impact": round(impact, 3),
        "risk_score": risk_score,
        "risk_band": band,
        "inputs": {
            "security_risk": sec_risk,
            "cv_risk": cv_risk,
            "fraud_risk": fraud_risk,
            "history_risk": hist_risk,
            "monetary_exposure": monetary_exposure,
            "policy_impact": policy_impact,
            "data_impact": data_impact,
        },
        "weights": {"likelihood": RISK_WEIGHTS, "impact": IMPACT_WEIGHTS},
    }
