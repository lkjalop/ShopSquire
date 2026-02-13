from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List


@dataclass
class AnomalyEvent:
    id: str
    domain: str  # refunds|orders|agent
    score: float
    context: Dict[str, Any]


class AnomalyDetector:
    """Statistical + ML ensemble (placeholder).

    Domains:
    - Refund velocity (user, merchant, product)
    - Order patterns (amount, frequency, geography)
    - Agent behavior (tool calls, escalations)

    Methods (planned):
    - Z-score for simple metrics
    - Isolation Forest for multivariate
    - Time-series anomaly (Prophet)
    """

    def detect(self, series: List[float], domain: str = "generic") -> List[AnomalyEvent]:
        import statistics as _st
        anomalies: List[AnomalyEvent] = []
        if not series:
            return anomalies
        mean = _st.mean(series)
        stdev = _st.pstdev(series) or 1.0
        for i, v in enumerate(series):
            z = abs((v - mean) / stdev)
            if z >= 3.0:
                anomalies.append(AnomalyEvent(id=f"{domain}-{i}", domain=domain, score=float(z), context={"index": i, "value": v}))
        return anomalies
