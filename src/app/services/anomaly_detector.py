from __future__ import annotations

import logging
import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

log = logging.getLogger(__name__)

try:
    import numpy as np  # type: ignore

    _HAS_NUMPY = True
except Exception:
    np = None  # type: ignore
    _HAS_NUMPY = False

try:
    from sklearn.ensemble import IsolationForest  # type: ignore
    from sklearn.neighbors import LocalOutlierFactor  # type: ignore

    _HAS_SKLEARN = True
except Exception:
    IsolationForest = None  # type: ignore
    LocalOutlierFactor = None  # type: ignore
    _HAS_SKLEARN = False

try:
    import pandas as pd  # type: ignore
    from prophet import Prophet  # type: ignore

    _HAS_PROPHET = True
except Exception:
    pd = None  # type: ignore
    Prophet = None  # type: ignore
    _HAS_PROPHET = False

log.info(
    "[AnomalyDetector] ML module inventory — numpy=%s sklearn=%s prophet=%s",
    _HAS_NUMPY,
    _HAS_SKLEARN,
    _HAS_PROPHET,
)


@dataclass
class AnomalyEvent:
    id: str
    domain: str
    score: float
    context: Dict[str, Any]


@dataclass
class AnomalyResult:
    domain: str
    value: float
    is_anomaly: bool
    confidence: float
    severity: str
    method_votes: Dict[str, bool] = field(default_factory=dict)
    z_score: Optional[float] = None
    plain_english: str = ""
    expected_range: Optional[Tuple[float, float]] = None
    deviation_ratio: Optional[float] = None

    def to_event(self, *, idx: int = -1) -> AnomalyEvent:
        return AnomalyEvent(
            id=f"{self.domain}-{idx if idx >= 0 else 'latest'}",
            domain=self.domain,
            score=float(self.confidence),
            context={
                "value": self.value,
                "severity": self.severity,
                "plain_english": self.plain_english,
                "z_score": self.z_score,
                "method_votes": self.method_votes,
                "expected_range": self.expected_range,
                "deviation_ratio": self.deviation_ratio,
            },
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "domain": self.domain,
            "value": self.value,
            "is_anomaly": self.is_anomaly,
            "confidence": round(self.confidence, 4),
            "severity": self.severity,
            "method_votes": dict(self.method_votes),
            "z_score": round(float(self.z_score), 4) if isinstance(self.z_score, (int, float)) else None,
            "plain_english": self.plain_english,
            "expected_range": list(self.expected_range) if self.expected_range else None,
            "deviation_ratio": round(float(self.deviation_ratio), 4) if isinstance(self.deviation_ratio, (int, float)) else None,
        }


class AnomalyDetector:
    """Ensemble anomaly detector with graceful fallback.

    Backward compatibility:
    - `detect(series, domain)` still returns `List[AnomalyEvent]`
    New API:
    - `detect_metrics(metrics, histories=...)` returns typed `AnomalyResult` objects
    - `detect_time_series(domain, series)` performs Prophet-based checks when available
    """

    MIN_SAMPLES_FOR_ML = 12
    MAX_HISTORY = 1000

    def __init__(self) -> None:
        self._history: Dict[str, List[float]] = defaultdict(list)

    def observe(self, domain: str, value: float) -> None:
        vals = self._history[domain]
        vals.append(float(value))
        if len(vals) > self.MAX_HISTORY:
            self._history[domain] = vals[-self.MAX_HISTORY :]

    def detect(self, series: List[float], domain: str = "generic") -> List[AnomalyEvent]:
        anomalies: List[AnomalyEvent] = []
        if not series:
            return anomalies
        results = self.score_series(series=series, domain=domain)
        for idx, result in enumerate(results):
            if result.is_anomaly:
                anomalies.append(result.to_event(idx=idx))
        return anomalies

    def score_series(self, *, series: Sequence[float], domain: str) -> List[AnomalyResult]:
        history: List[float] = []
        out: List[AnomalyResult] = []
        for value in series:
            history.append(float(value))
            self._history[domain] = history[-self.MAX_HISTORY :]
            out.append(self._score_single(domain=domain, value=float(value), history=history))
        return out

    def detect_metrics(
        self,
        metrics: Dict[str, float],
        *,
        histories: Optional[Dict[str, Sequence[float]]] = None,
    ) -> List[AnomalyResult]:
        results: List[AnomalyResult] = []
        history_map = histories or {}
        for domain, value in (metrics or {}).items():
            hist = [float(x) for x in (history_map.get(domain) or self._history.get(domain) or [])]
            hist.append(float(value))
            self._history[domain] = hist[-self.MAX_HISTORY :]
            result = self._score_single(domain=domain, value=float(value), history=hist)
            if result.is_anomaly:
                results.append(result)
        return results

    def detect_time_series(self, domain: str, series: List[Tuple[str, float]]) -> List[AnomalyResult]:
        if not series:
            return []
        if not _HAS_PROPHET or len(series) < max(self.MIN_SAMPLES_FOR_ML, 16):
            values = [float(v) for _, v in series]
            return [r for r in self.score_series(series=values, domain=domain) if r.is_anomaly]

        try:
            assert pd is not None and Prophet is not None
            df = pd.DataFrame(series, columns=["ds", "y"])
            df["ds"] = pd.to_datetime(df["ds"])
            model = Prophet(
                yearly_seasonality=False,
                weekly_seasonality=True,
                daily_seasonality=True,
                changepoint_prior_scale=0.05,
            )
            model.fit(df.iloc[:-1])
            forecast = model.predict(df[["ds"]])
            out: List[AnomalyResult] = []
            for idx, (_, row) in enumerate(df.iterrows()):
                lower = float(forecast.iloc[idx]["yhat_lower"])
                upper = float(forecast.iloc[idx]["yhat_upper"])
                value = float(row["y"])
                is_anomaly = value < lower or value > upper
                if not is_anomaly:
                    continue
                ratio = _ratio_against_band(value=value, lower=lower, upper=upper)
                confidence = min(1.0, 0.55 + ratio * 0.25)
                out.append(
                    AnomalyResult(
                        domain=domain,
                        value=value,
                        is_anomaly=True,
                        confidence=confidence,
                        severity=_severity_from_confidence(confidence),
                        method_votes={"prophet": True},
                        plain_english=_plain_english(domain, value, confidence, expected_range=(lower, upper)),
                        expected_range=(lower, upper),
                        deviation_ratio=ratio,
                    )
                )
            return out
        except Exception as exc:
            log.debug("Prophet anomaly detection failed for %s: %s", domain, exc)
            values = [float(v) for _, v in series]
            return [r for r in self.score_series(series=values, domain=domain) if r.is_anomaly]

    def _score_single(self, *, domain: str, value: float, history: Sequence[float]) -> AnomalyResult:
        votes: Dict[str, bool] = {}
        prior = [float(v) for v in history[:-1]]
        band = _expected_range(prior)
        z_score = _z_score(prior, value)

        if z_score is not None:
            votes["zscore"] = z_score >= 2.5

        if _HAS_SKLEARN and len(prior) >= self.MIN_SAMPLES_FOR_ML:
            try:
                assert np is not None and IsolationForest is not None
                iso = IsolationForest(
                    n_estimators=100,
                    contamination="auto",
                    random_state=42,
                )
                arr = np.array(prior).reshape(-1, 1)
                iso.fit(arr)
                score = float(iso.decision_function([[value]])[0])
                votes["isolation_forest"] = score < 0.0
            except Exception as exc:
                log.debug("IsolationForest failed for %s: %s", domain, exc)

            try:
                assert np is not None and LocalOutlierFactor is not None
                n_neighbors = min(20, max(2, len(prior) - 1))
                lof = LocalOutlierFactor(n_neighbors=n_neighbors, novelty=True)
                lof.fit(np.array(prior).reshape(-1, 1))
                pred = int(lof.predict([[value]])[0])
                votes["lof"] = pred == -1
            except Exception as exc:
                log.debug("LOF failed for %s: %s", domain, exc)

        if band is not None:
            lower, upper = band
            votes["band"] = value < lower or value > upper

        true_votes = sum(1 for flag in votes.values() if flag)
        total_votes = max(1, len(votes))
        is_anomaly = true_votes >= max(1, math.ceil(total_votes / 2.0))
        deviation_ratio = None
        if band is not None:
            deviation_ratio = _ratio_against_band(value=value, lower=band[0], upper=band[1])
        confidence = min(
            1.0,
            max(
                0.15,
                (true_votes / total_votes) * 0.7
                + (min(1.0, (deviation_ratio or 0.0) / 2.0) * 0.2)
                + (min(1.0, (z_score or 0.0) / 6.0) * 0.1),
            ),
        )
        if not is_anomaly:
            confidence = min(confidence, 0.49)

        return AnomalyResult(
            domain=domain,
            value=float(value),
            is_anomaly=is_anomaly,
            confidence=round(confidence, 4),
            severity=_severity_from_confidence(confidence) if is_anomaly else "low",
            method_votes=votes,
            z_score=z_score,
            plain_english=_plain_english(domain, value, confidence, expected_range=band),
            expected_range=band,
            deviation_ratio=deviation_ratio,
        )


def _expected_range(values: Sequence[float]) -> Optional[Tuple[float, float]]:
    if not values:
        return None
    if len(values) == 1:
        val = float(values[0])
        return (val * 0.8, val * 1.2)
    mean = sum(values) / len(values)
    variance = sum((float(v) - mean) ** 2 for v in values) / max(1, len(values))
    stdev = math.sqrt(max(variance, 1e-9))
    return (mean - 2.5 * stdev, mean + 2.5 * stdev)


def _z_score(values: Sequence[float], value: float) -> Optional[float]:
    if len(values) < 2:
        return None
    mean = sum(values) / len(values)
    variance = sum((float(v) - mean) ** 2 for v in values) / max(1, len(values))
    stdev = math.sqrt(max(variance, 1e-9))
    if stdev <= 0:
        return None
    return abs((float(value) - mean) / stdev)


def _ratio_against_band(*, value: float, lower: float, upper: float) -> float:
    if lower <= value <= upper:
        return 0.0
    width = max(upper - lower, 1e-6)
    if value > upper:
        return (value - upper) / width
    return (lower - value) / width


def _severity_from_confidence(confidence: float) -> str:
    if confidence >= 0.85:
        return "critical"
    if confidence >= 0.7:
        return "high"
    if confidence >= 0.55:
        return "medium"
    return "low"


def _plain_english(
    domain: str,
    value: float,
    confidence: float,
    *,
    expected_range: Optional[Tuple[float, float]],
) -> str:
    label = domain.replace("_", " ")
    if expected_range is None:
        return f"{label.capitalize()} is unusually high at {value:.2f}."
    lower, upper = expected_range
    if value > upper:
        return (
            f"{label.capitalize()} is above its expected range at {value:.2f}. "
            f"Normal range was approximately {lower:.2f} to {upper:.2f}."
        )
    if value < lower:
        return (
            f"{label.capitalize()} is below its expected range at {value:.2f}. "
            f"Normal range was approximately {lower:.2f} to {upper:.2f}."
        )
    if confidence >= 0.5:
        return f"{label.capitalize()} looks unusual at {value:.2f}."
    return f"{label.capitalize()} is within its expected range."


def build_hourly_series(values: Iterable[float]) -> List[Tuple[str, float]]:
    now = datetime.utcnow().replace(minute=0, second=0, microsecond=0)
    out: List[Tuple[str, float]] = []
    vals = [float(v) for v in values]
    start = now - timedelta(hours=max(0, len(vals) - 1))
    for idx, value in enumerate(vals):
        out.append(((start + timedelta(hours=idx)).isoformat(), value))
    return out
