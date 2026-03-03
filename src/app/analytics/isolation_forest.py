from __future__ import annotations

"""Isolation Forest utilities with graceful fallbacks.

Provides scoring helpers and a small `IsoForestDetector` wrapper that
uses `sklearn.ensemble.IsolationForest` when available and falls back to
robust z-score heuristics when not. All scoring returns a normalized
anomaly `score` in [0,1] and a coarse `label` in {minimal, low, medium, high}.
"""

from dataclasses import dataclass
import math
from typing import Any, Dict, List, Optional


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


def _score_isoforest(xs: List[float]) -> float:
    try:
        from sklearn.ensemble import IsolationForest  # type: ignore
        import numpy as np  # type: ignore

        X = np.array(xs, dtype=float).reshape(1, -1)
        baseline = np.zeros_like(X)
        data = np.vstack([baseline, X])
        clf = IsolationForest(n_estimators=50, contamination=0.1, random_state=42)
        clf.fit(data)
        raw = -clf.decision_function(X)[0]
        score = 1.0 / (1.0 + (2.71828 ** (-raw)))
        return max(0.0, min(1.0, float(score)))
    except Exception:
        try:
            import statistics as _st

            m = _st.mean(xs)
            sd = _st.pstdev(xs) or 1.0
            z = abs((m - 0.0) / sd)
            score = min(1.0, z / 5.0)
            return float(score)
        except Exception:
            return 0.0


@dataclass
class ScoreResult:
    score: float
    label: str
    details: Dict[str, Any]


class IsoForestDetector:
    """Small wrapper around sklearn's IsolationForest with graceful fallback."""

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
        if self._sklearn_available and self.model is not None:
            try:
                import numpy as _np  # type: ignore

                arr = _np.array(X, dtype=float)
                self.model.fit(arr)
                return True
            except Exception:
                return False
        return False

    def score(self, x: List[float]) -> ScoreResult:
        xs = list(map(float, x or []))
        raw = _score_isoforest(xs)
        return ScoreResult(score=raw, label=_label(raw), details={})


def score_fraud(features: Dict[str, Any]) -> Dict[str, Any]:
    xs = _prepare(features)
    score = _score_isoforest(xs)
    return {"score": score, "label": _label(score)}


def score_inventory(features: Dict[str, Any]) -> Dict[str, Any]:
    xs = _prepare(features)
    score = _score_isoforest(xs)
    return {"score": score, "label": _label(score)}


def score_agent_behavior(features: Dict[str, Any]) -> Dict[str, Any]:
    xs = _prepare(features)
    score = _score_isoforest(xs)
    return {"score": score, "label": _label(score)}
 


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
        import logging

        logging.getLogger("shopsquire.analytics.isoforest").exception("Failed building features_from_fraud_signals")
    return vals or [0.0]


def features_from_inventory(series: Dict[str, Any]) -> List[float]:
    vals = []
    try:
        vals.append(float(series.get("stock" ,0)))
        vals.append(float(series.get("stock_velocity", 0.0)))
        vals.append(float(series.get("daily_variance", 0.0)))
    except Exception:
        import logging

        logging.getLogger("shopsquire.analytics.isoforest").exception("Failed building features_from_inventory")
    return vals or [0.0]


def features_from_agent_behavior(stats: Dict[str, Any]) -> List[float]:
    vals = []
    try:
        vals.append(float(stats.get("tool_calls", 0)))
        vals.append(float(stats.get("avg_latency_ms", 0.0)))
        vals.append(float(stats.get("escalation_rate", 0.0)))
        vals.append(float(stats.get("errors", 0)))
    except Exception:
        import logging

        logging.getLogger("shopsquire.analytics.isoforest").exception("Failed building features_from_agent_behavior")
    return vals or [0.0]


def score_fraud(session: Dict[str, Any], cv: Dict[str, Any], policy: Dict[str, Any], model: Optional[IsoForestDetector] = None) -> ScoreResult:
    model = model or IsoForestDetector()
    X = [features_from_fraud_signals(session, cv, policy)]
    try:
        model.fit(X)
    except Exception:
        import logging

        logging.getLogger("shopsquire.analytics.isoforest").exception("Failed fitting IsoForest model")
    s = model.score(X)
    sc = float(s[0]) if s else 0.0
    return ScoreResult(score=sc, label=IsoForestDetector.label(sc), details={"features": X[0]})


def score_inventory(series: Dict[str, Any], model: Optional[IsoForestDetector] = None) -> ScoreResult:
    model = model or IsoForestDetector()
    X = [features_from_inventory(series)]
    try:
        model.fit(X)
    except Exception:
        import logging

        logging.getLogger("shopsquire.analytics.isoforest").exception("Failed fitting IsoForest model for inventory")
    s = model.score(X)
    sc = float(s[0]) if s else 0.0
    return ScoreResult(score=sc, label=IsoForestDetector.label(sc), details={"features": X[0]})


def score_agent_behavior(stats: Dict[str, Any], model: Optional[IsoForestDetector] = None) -> ScoreResult:
    model = model or IsoForestDetector()
    X = [features_from_agent_behavior(stats)]
    try:
        model.fit(X)
    except Exception:
        import logging

        logging.getLogger("shopsquire.analytics.isoforest").exception("Failed fitting IsoForest model for agent behavior")
    s = model.score(X)
    sc = float(s[0]) if s else 0.0
    return ScoreResult(score=sc, label=IsoForestDetector.label(sc), details={"features": X[0]})
