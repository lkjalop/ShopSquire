from __future__ import annotations

"""Agent behavior anomaly detection using IsolationForest.

Builds simple features from agent metrics snapshots and scores anomalies.
Emits a dict: {score: float, label: str, features: dict}.
"""

from typing import Dict, Any

try:
    from src.app.services import agent_metrics
except Exception:
    agent_metrics = None

try:
    from src.app.analytics.isolation_forest import score_agent_behavior
except Exception:
    def score_agent_behavior(_features: Dict[str, Any]) -> Dict[str, Any]:
        return {"score": 0.0, "label": "minimal"}


def detect_behavior_anomaly() -> Dict[str, Any]:
    feats: Dict[str, Any] = {}
    try:
        snap = agent_metrics.snapshot() if agent_metrics is not None else {"counters": {}, "histograms": {}}
        ctrs = snap.get("counters") if isinstance(snap, dict) else {}
        hists = snap.get("histograms") if isinstance(snap, dict) else {}
        # Counters
        feats["recommendation_calls"] = float(ctrs.get("recommendation_calls", 0))
        feats["parse_failures"] = float(ctrs.get("parse_failures", 0))
        feats["hallucination_count"] = float(ctrs.get("hallucination_count", 0))
        feats["human_review_queued"] = float(ctrs.get("human_review_queued", 0))
        # Latency (average last N)
        def avg_hist(name: str) -> float:
            vals = hists.get(name) or []
            if not isinstance(vals, list) or not vals:
                return 0.0
            try:
                return float(sum(vals) / len(vals))
            except Exception:
                return 0.0
        feats["recommendation_latency_avg_s"] = avg_hist("recommendation_latency_s")
        feats["human_review_latency_avg_s"] = avg_hist("human_review_latency_s")
    except Exception:
        pass
    score = score_agent_behavior(feats)
    return {"score": float(score.get("score") or 0.0), "label": str(score.get("label") or "minimal"), "features": feats}
