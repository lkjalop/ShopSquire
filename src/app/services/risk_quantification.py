from __future__ import annotations

import hashlib
import math
import random
from typing import Any, Dict, List


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


# ---------------------------------------------------------------------------
# FAIR Risk Model — Monte Carlo simulation
# ---------------------------------------------------------------------------

def _pert_sample(low: float, mode: float, high: float) -> float:
    """Sample from a PERT (modified Beta) distribution."""
    if high <= low:
        return mode
    lam = 4.0
    alpha = 1 + lam * ((mode - low) / (high - low))
    beta_ = 1 + lam * ((high - mode) / (high - low))
    # Use inverse-transform via Python's betavariate
    x = random.betavariate(alpha, beta_)
    return low + x * (high - low)


def fair_monte_carlo(
    *,
    # Threat Event Frequency (TEF): how many times/year
    tef_low: float = 1.0,
    tef_mode: float = 5.0,
    tef_high: float = 20.0,
    # Vulnerability (probability that threat becomes loss event)
    vuln_low: float = 0.1,
    vuln_mode: float = 0.3,
    vuln_high: float = 0.7,
    # Primary Loss Magnitude ($)
    plm_low: float = 500.0,
    plm_mode: float = 5_000.0,
    plm_high: float = 50_000.0,
    # Secondary Loss Magnitude ($)
    slm_low: float = 0.0,
    slm_mode: float = 2_000.0,
    slm_high: float = 20_000.0,
    # Secondary Loss Event Frequency (probability of secondary loss)
    slef_low: float = 0.05,
    slef_mode: float = 0.15,
    slef_high: float = 0.4,
    # Asset value for context
    asset_value: float = 100_000.0,
    simulations: int = 5_000,
    seed: int | None = None,
) -> Dict[str, Any]:
    """Run FAIR Monte Carlo risk quantification.

    Returns ALE distribution (mean, percentiles), Loss Event Frequency,
    Single Loss Expectancy stats, and per-percentile exposure.
    """
    if seed is not None:
        random.seed(seed)

    simulations = min(max(simulations, 100), 50_000)

    ale_samples: List[float] = []
    lef_samples: List[float] = []
    sle_samples: List[float] = []

    for _ in range(simulations):
        tef = _pert_sample(tef_low, tef_mode, tef_high)
        vuln = _pert_sample(vuln_low, vuln_mode, vuln_high)
        vuln = max(0.0, min(1.0, vuln))

        lef = tef * vuln  # Loss Event Frequency
        lef_samples.append(lef)

        plm = _pert_sample(plm_low, plm_mode, plm_high)
        slm = _pert_sample(slm_low, slm_mode, slm_high)
        slef = _pert_sample(slef_low, slef_mode, slef_high)
        slef = max(0.0, min(1.0, slef))

        sle = plm + (slm * slef)  # Single Loss Expectancy
        sle_samples.append(sle)

        ale = lef * sle  # Annualized Loss Expectancy
        ale_samples.append(ale)

    ale_sorted = sorted(ale_samples)
    lef_sorted = sorted(lef_samples)
    sle_sorted = sorted(sle_samples)

    def _percentile(data: List[float], p: float) -> float:
        idx = int(len(data) * p / 100.0)
        idx = max(0, min(idx, len(data) - 1))
        return round(data[idx], 2)

    def _stats(data: List[float], label: str) -> Dict[str, Any]:
        mean = sum(data) / len(data) if data else 0.0
        return {
            "mean": round(mean, 2),
            "p5": _percentile(data, 5),
            "p25": _percentile(data, 25),
            "p50": _percentile(data, 50),
            "p75": _percentile(data, 75),
            "p90": _percentile(data, 90),
            "p95": _percentile(data, 95),
            "min": round(data[0], 2) if data else 0,
            "max": round(data[-1], 2) if data else 0,
        }

    ale_mean = sum(ale_samples) / len(ale_samples)
    ale_p95 = _percentile(ale_sorted, 95)

    # Risk band based on ALE as % of asset value
    ale_ratio = ale_mean / asset_value if asset_value > 0 else 0
    if ale_ratio > 0.15:
        risk_band = "critical"
    elif ale_ratio > 0.05:
        risk_band = "high"
    elif ale_ratio > 0.01:
        risk_band = "medium"
    else:
        risk_band = "low"

    # Build a simple histogram (10 buckets)
    bucket_count = 10
    ale_min = ale_sorted[0] if ale_sorted else 0
    ale_max = ale_sorted[-1] if ale_sorted else 1
    bucket_width = (ale_max - ale_min) / bucket_count if ale_max > ale_min else 1
    histogram: List[Dict[str, Any]] = []
    for i in range(bucket_count):
        lo = ale_min + i * bucket_width
        hi = lo + bucket_width
        count = sum(1 for v in ale_samples if lo <= v < hi) if i < bucket_count - 1 else sum(1 for v in ale_samples if lo <= v <= hi)
        histogram.append({"bucket_low": round(lo, 2), "bucket_high": round(hi, 2), "count": count})

    return {
        "model": "fair_monte_carlo",
        "simulations": simulations,
        "asset_value": asset_value,
        "risk_band": risk_band,
        "ale": _stats(ale_sorted, "ALE"),
        "lef": _stats(lef_sorted, "LEF"),
        "sle": _stats(sle_sorted, "SLE"),
        "ale_histogram": histogram,
        "inputs": {
            "tef": {"low": tef_low, "mode": tef_mode, "high": tef_high},
            "vulnerability": {"low": vuln_low, "mode": vuln_mode, "high": vuln_high},
            "primary_loss": {"low": plm_low, "mode": plm_mode, "high": plm_high},
            "secondary_loss": {"low": slm_low, "mode": slm_mode, "high": slm_high},
            "secondary_loss_freq": {"low": slef_low, "mode": slef_mode, "high": slef_high},
        },
    }


def fair_from_signals(
    *,
    security: Dict[str, Any] | None = None,
    cv_analysis: Dict[str, Any] | None = None,
    fraud: Dict[str, Any] | None = None,
    monetary_exposure: float | None = None,
    simulations: int = 5_000,
) -> Dict[str, Any]:
    """Derive FAIR input parameters from existing signal data and run Monte Carlo."""
    security = security or {}
    cv_analysis = cv_analysis or {}
    fraud = fraud or {}

    # Derive TEF from signal count
    signal_count = len(security.get("signals", []))
    tef_mode = max(1.0, signal_count * 2.0)
    tef_low = max(0.5, tef_mode * 0.3)
    tef_high = tef_mode * 3.0

    # Derive vulnerability from fraud level
    fraud_level = (fraud.get("level") or "low").lower()
    vuln_map = {"minimal": 0.1, "low": 0.2, "medium": 0.45, "high": 0.7}
    vuln_mode = vuln_map.get(fraud_level, 0.2)
    vuln_low = max(0.01, vuln_mode * 0.5)
    vuln_high = min(0.95, vuln_mode * 2.0)

    # Derive loss magnitudes from monetary exposure
    exposure = float(monetary_exposure or 1000)
    plm_mode = exposure
    plm_low = exposure * 0.2
    plm_high = exposure * 3.0

    # CV severity influences secondary loss
    cv_sev = (cv_analysis.get("severity") or "minor").lower()
    slm_mult = {"minor": 0.3, "moderate": 0.6, "major": 1.0, "high": 1.5, "critical": 2.0}.get(cv_sev, 0.5)
    slm_mode = exposure * slm_mult
    slm_low = slm_mode * 0.1
    slm_high = slm_mode * 3.0

    return fair_monte_carlo(
        tef_low=tef_low, tef_mode=tef_mode, tef_high=tef_high,
        vuln_low=vuln_low, vuln_mode=vuln_mode, vuln_high=vuln_high,
        plm_low=plm_low, plm_mode=plm_mode, plm_high=plm_high,
        slm_low=slm_low, slm_mode=slm_mode, slm_high=slm_high,
        asset_value=exposure * 10,
        simulations=simulations,
    )
