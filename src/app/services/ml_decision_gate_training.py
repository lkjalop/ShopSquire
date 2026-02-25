from __future__ import annotations

import json
import random
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from sqlalchemy import text

from src.app.models.db import db_session


POSITIVE_OUTCOMES = {
    "true_positive",
    "correct",
    "effective",
    "success",
    "false_negative",
    "missed",
}
NEGATIVE_OUTCOMES = {
    "false_positive",
    "incorrect",
    "benign",
}


def _clamp01(x: float) -> float:
    if x < 0.0:
        return 0.0
    if x > 1.0:
        return 1.0
    return x


def _sigmoid(x: float) -> float:
    import math

    if x < -40.0:
        return 0.0
    if x > 40.0:
        return 1.0
    return 1.0 / (1.0 + math.exp(-x))


@dataclass
class GateTrainingSample:
    tenant_id: str
    label: int
    features: Dict[str, float]
    decision_id: str | None = None


def _json_load(v: Any, default: Any) -> Any:
    if v is None:
        return default
    if isinstance(v, (dict, list)):
        return v
    try:
        return json.loads(str(v))
    except Exception:
        return default


def _label_from_ground_truth(ground_truth: str | None) -> int | None:
    g = str(ground_truth or "").strip().lower()
    if g in ("true_positive", "false_negative"):
        return 1
    if g in ("false_positive",):
        return 0
    return None


def _label_from_outcome(outcome_value: str | None) -> int | None:
    ov = str(outcome_value or "").strip().lower()
    if ov in POSITIVE_OUTCOMES:
        return 1
    if ov in NEGATIVE_OUTCOMES:
        return 0
    return None


def _sanitize_features(features: Dict[str, Any]) -> Dict[str, float]:
    out: Dict[str, float] = {}
    for k, v in (features or {}).items():
        try:
            fv = float(v)
        except Exception:
            continue
        if fv != fv:  # NaN guard
            continue
        out[str(k)] = _clamp01(fv)
    return out


def _latest_outcomes(limit: int = 25000) -> Dict[str, str]:
    rows = []
    try:
        with db_session() as db:
            rows = db.execute(
                text(
                    """
                    SELECT decision_id, outcome_value, valid_from
                    FROM posthoc_outcomes
                    WHERE decision_id IS NOT NULL
                    ORDER BY valid_from DESC
                    LIMIT :limit
                    """
                ),
                {"limit": int(max(500, limit))},
            ).fetchall()
    except Exception:
        return {}
    out: Dict[str, str] = {}
    for r in rows or []:
        did = str((r[0] or "")).strip()
        if not did or did in out:
            continue
        out[did] = str(r[1] or "")
    return out


def collect_training_samples(
    *,
    tenant_id: str | None = None,
    limit: int = 8000,
) -> List[GateTrainingSample]:
    latest_outcomes = _latest_outcomes(limit=max(limit * 3, 3000))
    rows = []
    try:
        with db_session() as db:
            rows = db.execute(
                text(
                    """
                    SELECT tenant_id, evidence_json, ground_truth
                    FROM email_security_incidents
                    WHERE (:tenant_id IS NULL OR tenant_id = :tenant_id)
                    ORDER BY created_at DESC
                    LIMIT :limit
                    """
                ),
                {"tenant_id": tenant_id, "limit": int(max(200, limit))},
            ).fetchall()
    except Exception:
        rows = []

    out: List[GateTrainingSample] = []
    for r in rows or []:
        t_id = str(r[0] or "default")
        evidence = _json_load(r[1], {})
        if not isinstance(evidence, dict):
            continue

        features = _sanitize_features(_json_load(evidence.get("ml_features"), {}))
        if not features:
            continue

        label = _label_from_ground_truth(r[2])
        did = str(evidence.get("decision_id") or evidence.get("trace_id") or "").strip() or None
        if label is None and did:
            label = _label_from_outcome(latest_outcomes.get(did))
        if label is None:
            continue
        out.append(GateTrainingSample(tenant_id=t_id, label=int(label), features=features, decision_id=did))
    return out


def _feature_union(samples: Sequence[GateTrainingSample]) -> List[str]:
    keys: set[str] = set()
    for s in samples:
        keys.update((s.features or {}).keys())
    return sorted(keys)


def _fit_logistic(
    xs: Sequence[Sequence[float]],
    ys: Sequence[int],
    *,
    epochs: int = 320,
    lr: float = 0.16,
    l2: float = 0.0008,
    seed: int = 42,
) -> Tuple[List[float], float]:
    if not xs:
        return [], 0.0
    n_features = len(xs[0])
    w = [0.0] * n_features
    b = 0.0
    idx = list(range(len(xs)))
    rnd = random.Random(seed)
    for _ in range(max(10, epochs)):
        rnd.shuffle(idx)
        for i in idx:
            x = xs[i]
            y = float(ys[i])
            z = b
            for j in range(n_features):
                z += (w[j] * float(x[j]))
            p = _sigmoid(z)
            err = (p - y)
            for j in range(n_features):
                w[j] -= lr * ((err * float(x[j])) + (l2 * w[j]))
            b -= lr * err
    return w, b


def _metric_summary(xs: Sequence[Sequence[float]], ys: Sequence[int], weights: Sequence[float], bias: float) -> Dict[str, float]:
    if not xs:
        return {"samples": 0, "positive_rate": 0.0, "accuracy": 0.0, "precision": 0.0, "recall": 0.0}
    tp = fp = tn = fn = 0
    for i, x in enumerate(xs):
        z = float(bias)
        for j, w in enumerate(weights):
            z += float(w) * float(x[j])
        p = _sigmoid(z)
        pred = 1 if p >= 0.5 else 0
        y = int(ys[i])
        if pred == 1 and y == 1:
            tp += 1
        elif pred == 1 and y == 0:
            fp += 1
        elif pred == 0 and y == 0:
            tn += 1
        else:
            fn += 1
    total = max(1, tp + tn + fp + fn)
    return {
        "samples": float(total),
        "positive_rate": round(float(tp + fn) / float(total), 4),
        "accuracy": round(float(tp + tn) / float(total), 4),
        "precision": round(float(tp) / float(max(1, tp + fp)), 4),
        "recall": round(float(tp) / float(max(1, tp + fn)), 4),
    }


def _quality_score(metrics: Dict[str, float]) -> float:
    acc = float(metrics.get("accuracy", 0.0) or 0.0)
    precision = float(metrics.get("precision", 0.0) or 0.0)
    recall = float(metrics.get("recall", 0.0) or 0.0)
    pos_rate = float(metrics.get("positive_rate", 0.5) or 0.5)
    balance_penalty = min(0.4, abs(pos_rate - 0.5))
    score = (0.4 * acc) + (0.3 * precision) + (0.3 * recall) - (0.25 * balance_penalty)
    return round(max(0.0, min(1.0, score)), 4)


def _fit_platt(scores: Sequence[float], ys: Sequence[int], *, epochs: int = 240, lr: float = 0.09) -> Tuple[float, float]:
    if not scores:
        return 1.0, 0.0
    x2 = [[float(s)] for s in scores]
    w, b = _fit_logistic(x2, ys, epochs=epochs, lr=lr, l2=0.0004, seed=11)
    a = float(w[0]) if w else 1.0
    return a, float(b)


def train_gate_from_samples(
    samples: Sequence[GateTrainingSample],
    *,
    domain: str = "email_security",
    min_samples: int = 40,
    min_tenant_samples: int = 25,
) -> Dict[str, Any]:
    if len(samples) < min_samples:
        return {
            "updated": False,
            "reason": "insufficient_samples",
            "sample_size": len(samples),
            "required_min_samples": min_samples,
        }

    features = _feature_union(samples)
    xs: List[List[float]] = []
    ys: List[int] = []
    for s in samples:
        xs.append([float(s.features.get(k, 0.0) or 0.0) for k in features])
        ys.append(int(s.label))
    w, b = _fit_logistic(xs, ys)
    metrics = _metric_summary(xs, ys, w, b)

    scores = []
    for x in xs:
        z = float(b)
        for j, ww in enumerate(w):
            z += float(ww) * float(x[j])
        scores.append(_sigmoid(z))
    cal_a, cal_b = _fit_platt(scores, ys)

    per_tenant: Dict[str, Dict[str, Any]] = {}
    buckets: Dict[str, List[int]] = {}
    for i, s in enumerate(samples):
        buckets.setdefault(str(s.tenant_id or "default"), []).append(i)
    for tenant, idxs in buckets.items():
        if len(idxs) < min_tenant_samples:
            continue
        t_scores = [scores[i] for i in idxs]
        t_labels = [ys[i] for i in idxs]
        a, bb = _fit_platt(t_scores, t_labels)
        t_metrics = _metric_summary([[s] for s in t_scores], t_labels, [1.0], 0.0)
        t_quality = _quality_score(t_metrics)
        per_tenant[tenant] = {
            "method": "platt",
            "params": {"a": round(float(a), 6), "b": round(float(bb), 6)},
            "sample_size": len(idxs),
            "quality_score": t_quality,
            "metrics": t_metrics,
        }

    coef = {k: round(float(w[i]), 6) for i, k in enumerate(features)}
    return {
        "updated": True,
        "domain": domain,
        "sample_size": len(samples),
        "feature_count": len(features),
        "artifact": {
            "version": "ml_decision_gate_v1",
            "trained_at": datetime.now(timezone.utc).isoformat(),
            "domains": {
                domain: {
                    "model": {
                        "kind": "logistic",
                        "bias": round(float(b), 6),
                        "coefficients": coef,
                        "metrics": metrics,
                        "quality_score": _quality_score(metrics),
                        "sample_size": len(samples),
                    },
                    "calibration": {
                        "method": "platt",
                        "params": {"a": round(float(cal_a), 6), "b": round(float(cal_b), 6)},
                        "sample_size": len(samples),
                    },
                    "calibration_policy": {
                        "tenant_min_samples": int(min_tenant_samples),
                        "tenant_min_quality": 0.55,
                    },
                    "tenant_calibration": per_tenant,
                }
            },
        },
    }


def train_gate_from_db(
    *,
    domain: str = "email_security",
    tenant_id: str | None = None,
    limit: int = 8000,
    min_samples: int = 40,
    min_tenant_samples: int = 25,
) -> Dict[str, Any]:
    samples = collect_training_samples(tenant_id=tenant_id, limit=limit)
    result = train_gate_from_samples(
        samples,
        domain=domain,
        min_samples=min_samples,
        min_tenant_samples=min_tenant_samples,
    )
    result["tenant_id"] = tenant_id
    result["collected_samples"] = len(samples)
    return result


def save_gate_artifact(artifact: Dict[str, Any], *, output_path: str) -> str:
    out = Path(str(output_path)).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(artifact, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(out)
