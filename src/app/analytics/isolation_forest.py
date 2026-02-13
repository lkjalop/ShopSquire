from __future__ import annotations

"""Isolation Forest utilities with graceful fallbacks.

Provides three scoring helpers:
- score_fraud(features: dict) -> {score: float, label: str}
- score_inventory(features: dict) -> {score: float, label: str}
- score_agent_behavior(features: dict) -> {score: float, label: str}

If scikit-learn is unavailable, uses robust z-score heuristics.
All functions expect a dict of numeric features and return a normalized
anomaly score in [0,1] and a coarse label: minimal|low|medium|high.
"""

from typing import Dict, Any, List, Tuple


def _label(score: float) -> str:
    if score >= 0.7:
        return "high"
    if score >= 0.4:
        return "medium"
    if score >= 0.2:
        return "low"
    return "minimal"


def _prepare(features: Dict[str, Any]) -> List[float]:
    xs: List[float] = []
    for k, v in (features or {}).items():
        try:
            xs.append(float(v))
        except Exception:
            xs.append(0.0)
    if not xs:
        xs = [0.0]
    return xs


def _score_isoforest(xs: List[float]) -> float:
    try:
        from sklearn.ensemble import IsolationForest  # type: ignore
        import numpy as np  # type: ignore
        X = np.array(xs, dtype=float).reshape(1, -1)
        # Fit on a trivial synthetic baseline (zero vector) + current vector
        baseline = np.zeros_like(X)
        data = np.vstack([baseline, X])
        clf = IsolationForest(n_estimators=50, contamination=0.1, random_state=42)
        clf.fit(data)
        # Higher anomaly -> higher score; map decision_function to [0,1]
        raw = -clf.decision_function(X)[0]
        # Normalize via simple squashing
        score = 1.0 / (1.0 + (2.71828 ** (-raw)))
        return max(0.0, min(1.0, float(score)))
    except Exception:
        # Fallback to robust z-score heuristic
        try:
            import statistics as _st
            m = _st.mean(xs)
            sd = _st.pstdev(xs) or 1.0
            z = abs((m - 0.0) / sd)  # distance from baseline 0.0
            score = min(1.0, z / 5.0)
            return float(score)
        except Exception:
            return 0.0


def score_fraud(features: Dict[str, Any]) -> Dict[str, Any]:
    """Fraud anomaly score based on multivariate signals.

    Example features: {
      "velocity": 3.2, "geo_mismatch": 1, "device_change": 1,
      "cv_blur": 0.2, "phash_dup": 1, "approval_required": 1
    }
    """
    xs = _prepare(features)
    score = _score_isoforest(xs)
    return {"score": score, "label": _label(score)}


def score_inventory(features: Dict[str, Any]) -> Dict[str, Any]:
    """Inventory anomaly: stock velocity, variance, days of cover, etc."""
    xs = _prepare(features)
    score = _score_isoforest(xs)
    return {"score": score, "label": _label(score)}


def score_agent_behavior(features: Dict[str, Any]) -> Dict[str, Any]:
    """Agent behavior anomaly: tool_calls, avg_latency_ms, escalation_rate, error_rate."""
    xs = _prepare(features)
    score = _score_isoforest(xs)
    return {"score": score, "label": _label(score)}
from __future__ import annotations

"""Isolation Forest utilities (graceful, optional dependencies).

Provides a unified wrapper `IsoForestDetector` that attempts to use
`sklearn.ensemble.IsolationForest` when available, and falls back to
robust z-score heuristics when not.

Includes domain-specific feature mappers for:
- fraud (session + CV + policy signals)
- inventory (stock velocity + variance)
- agent behavior (tool calls, latencies, escalations)

This module is designed to be non-blocking and safe: if dependencies are
missing or fitting fails, scoring returns neutral outputs.
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import math


def _robust_zscores(values: List[float]) -> List[float]:
    if not values:
        return []
    try:
        import statistics as _st

        median = _st.median(values)
        mad = _st.median([abs(v - median) for v in values]) or 1.0
        return [abs((v - median) / (1.4826 * mad)) for v in values]
    except Exception:
        mean = sum(values) / max(len(values), 1)
        var = sum((v - mean) ** 2 for v in values) / max(len(values), 1)
        stdev = math.sqrt(var) or 1.0
        return [abs((v - mean) / stdev) for v in values]


@dataclass
class ScoreResult:
    score: float  # 0-1 anomaly score (higher = more anomalous)
    label: str    # minimal|low|medium|high
    details: Dict[str, Any]


class IsoForestDetector:
    """Unified IsolationForest wrapper with graceful fallbacks.

    Note: `sklearn` IsolationForest is batch-trained; online updates are not
    supported. For online scenarios, consider integrating PyOD+SUOD or PySAD.
    """

    def __init__(self, n_estimators: int = 100, contamination: Optional[float] = None, random_state: int = 42):
        self.model = None
        self._sklearn_available = False
        try:
            from sklearn.ensemble import IsolationForest  # type: ignore

            self.model = IsolationForest(n_estimators=n_estimators, contamination=contamination, random_state=random_state)
            self._sklearn_available = True
        except Exception:
            self.model = None
            self._sklearn_available = False

    def fit(self, X: List[List[float]]) -> bool:
        if not X:
            return False
        try:
            if self._sklearn_available and self.model is not None:
                self.model.fit(X)
                return True
            # No model: nothing to fit; we use heuristic scoring later
            return True
        except Exception:
            return False

    def score(self, X: List[List[float]]) -> List[float]:
        if not X:
            return []
        try:
            if self._sklearn_available and self.model is not None:
                # IsolationForest returns negative scores for anomalies; invert + normalize
                raw = self.model.decision_function(X)  # higher is more normal
                # Normalize to 0..1 anomaly (1 = most anomalous)
                mn, mx = (min(raw), max(raw)) if raw.size else (0.0, 0.0)
                rng = (mx - mn) or 1.0
                return [max(0.0, min(1.0, 1.0 - ((r - mn) / rng))) for r in raw]
        except Exception:
            pass
        # Heuristic fallback: robust z-score per vector magnitude
        mags = [sum(abs(v) for v in vec) for vec in X]
        zs = _robust_zscores(mags)
        # Map z>=3 to ~1.0, z~0 to ~0.0
        return [max(0.0, min(1.0, z / 4.0)) for z in zs]

    @staticmethod
    def label(score: float) -> str:
        if score >= 0.7:
            return "high"
        if score >= 0.4:
            return "medium"
        if score >= 0.2:
            return "low"
        return "minimal"


# ---------------- Domain feature mappers ----------------

def features_from_fraud_signals(session: Dict[str, Any], cv: Dict[str, Any], policy: Dict[str, Any]) -> List[float]:
    # Basic engineered features (extendable):
    vals = []
    try:
        vals.append(float(session.get("purchases_last_hour", 0)))
        vals.append(float(session.get("returns_last_30_days", 0)))
        vals.append(1.0 if (session.get("ip_country") != session.get("shipping_country")) else 0.0)
        vals.append(1.0 if session.get("device_changed_mid_session") else 0.0)
        vals.append(float(cv.get("blur_score") or 0.0))
        vals.append(1.0 if cv.get("phash_duplicate") else 0.0)
        vals.append(1.0 if (policy.get("approval_required") or False) else 0.0)
    except Exception:
        pass
    return vals or [0.0]


def features_from_inventory(series: Dict[str, Any]) -> List[float]:
    vals = []
    try:
        vals.append(float(series.get("stock" ,0)))
        vals.append(float(series.get("stock_velocity", 0.0)))
        vals.append(float(series.get("daily_variance", 0.0)))
    except Exception:
        pass
    return vals or [0.0]


def features_from_agent_behavior(stats: Dict[str, Any]) -> List[float]:
    vals = []
    try:
        vals.append(float(stats.get("tool_calls", 0)))
        vals.append(float(stats.get("avg_latency_ms", 0.0)))
        vals.append(float(stats.get("escalation_rate", 0.0)))
        vals.append(float(stats.get("errors", 0)))
    except Exception:
        pass
    return vals or [0.0]


def score_fraud(session: Dict[str, Any], cv: Dict[str, Any], policy: Dict[str, Any], model: Optional[IsoForestDetector] = None) -> ScoreResult:
    model = model or IsoForestDetector()
    X = [features_from_fraud_signals(session, cv, policy)]
    try:
        model.fit(X)
    except Exception:
        pass
    s = model.score(X)
    sc = float(s[0]) if s else 0.0
    return ScoreResult(score=sc, label=IsoForestDetector.label(sc), details={"features": X[0]})


def score_inventory(series: Dict[str, Any], model: Optional[IsoForestDetector] = None) -> ScoreResult:
    model = model or IsoForestDetector()
    X = [features_from_inventory(series)]
    try:
        model.fit(X)
    except Exception:
        pass
    s = model.score(X)
    sc = float(s[0]) if s else 0.0
    return ScoreResult(score=sc, label=IsoForestDetector.label(sc), details={"features": X[0]})


def score_agent_behavior(stats: Dict[str, Any], model: Optional[IsoForestDetector] = None) -> ScoreResult:
    model = model or IsoForestDetector()
    X = [features_from_agent_behavior(stats)]
    try:
        model.fit(X)
    except Exception:
        pass
    s = model.score(X)
    sc = float(s[0]) if s else 0.0
    return ScoreResult(score=sc, label=IsoForestDetector.label(sc), details={"features": X[0]})
