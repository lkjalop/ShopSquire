from __future__ import annotations

import json
import math
import os
import hashlib
from functools import lru_cache
from typing import Any, Dict, Tuple

from src.app.services.confidence_calibration import calibrate_confidence


def _clamp01(x: float) -> float:
    if x < 0.0:
        return 0.0
    if x > 1.0:
        return 1.0
    return x


def _sigmoid(x: float) -> float:
    try:
        if x < -40.0:
            return 0.0
        if x > 40.0:
            return 1.0
        return 1.0 / (1.0 + math.exp(-x))
    except Exception:
        return _clamp01(x)


def _default_model_path() -> str:
    return os.getenv("ML_DECISION_GATE_MODEL_PATH", "config/ml_decision_gate_model.json")


def _default_pointer_path() -> str:
    return os.getenv("ML_DECISION_GATE_ACTIVE_POINTER_PATH", "config/ml_decision_gate_active.json")


def _coerce_json_obj(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


@lru_cache(maxsize=4)
def _load_model_artifact(path: str, mtime: float) -> Dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def load_model_artifact(path: str | None = None) -> Dict[str, Any]:
    p = str(path or _resolve_active_model_path()).strip()
    if not p:
        return {}
    if not _artifact_integrity_ok(p):
        return {}
    try:
        mtime = float(os.path.getmtime(p))
    except Exception:
        return {}
    return _load_model_artifact(p, mtime)


def _select_domain_cfg(artifact: Dict[str, Any], domain: str) -> Dict[str, Any]:
    domains = _coerce_json_obj((artifact or {}).get("domains"))
    return _coerce_json_obj(domains.get(domain))


def _apply_platt(x: float, a: float, b: float) -> float:
    return _clamp01(_sigmoid((a * x) + b))


def _resolve_calibration(
    *,
    raw_score: float,
    domain_cfg: Dict[str, Any],
    tenant_id: str | None,
) -> Tuple[float | None, str]:
    min_samples = int(_coerce_json_obj(domain_cfg.get("calibration_policy")).get("tenant_min_samples", 25) or 25)
    min_quality = float(_coerce_json_obj(domain_cfg.get("calibration_policy")).get("tenant_min_quality", 0.55) or 0.55)
    tenant_key = str(tenant_id or "").strip()
    tenant_cfg = _coerce_json_obj(_coerce_json_obj(domain_cfg.get("tenant_calibration")).get(tenant_key))
    tenant_samples = int(tenant_cfg.get("sample_size", 0) or 0)
    tenant_quality = float(tenant_cfg.get("quality_score", 1.0) or 0.0)
    if (
        str(tenant_cfg.get("method") or "").lower() == "platt"
        and tenant_samples >= min_samples
        and tenant_quality >= min_quality
    ):
        params = _coerce_json_obj(tenant_cfg.get("params"))
        return _apply_platt(raw_score, float(params.get("a", 1.0)), float(params.get("b", 0.0))), "tenant_platt"

    global_cfg = _coerce_json_obj(domain_cfg.get("calibration"))
    if str(global_cfg.get("method") or "").lower() == "platt":
        params = _coerce_json_obj(global_cfg.get("params"))
        return _apply_platt(raw_score, float(params.get("a", 1.0)), float(params.get("b", 0.0))), "global_platt"
    return None, "none"


def _resolve_active_model_path() -> str:
    explicit = str(os.getenv("ML_DECISION_GATE_MODEL_PATH", "") or "").strip()
    # Explicit model path must win for testability and deterministic rollouts.
    if explicit:
        return explicit
    pointer_path = _default_pointer_path()
    if os.path.exists(pointer_path):
        try:
            with open(pointer_path, "r", encoding="utf-8") as f:
                p = json.load(f)
            if isinstance(p, dict):
                active = str(p.get("active_path") or "").strip()
                if active:
                    return active
        except Exception:
            pass
    return _default_model_path()


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(8192)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _artifact_integrity_ok(path: str) -> bool:
    pointer_path = _default_pointer_path()
    if not os.path.exists(path):
        return False
    if not os.path.exists(pointer_path):
        return True
    try:
        with open(pointer_path, "r", encoding="utf-8") as f:
            p = json.load(f)
        if not isinstance(p, dict):
            return True
        expected = str(p.get("active_checksum_sha256") or "").strip().lower()
        active_path = str(p.get("active_path") or "").strip()
        if not expected or not active_path:
            return True
        if os.path.normcase(os.path.abspath(active_path)) != os.path.normcase(os.path.abspath(path)):
            return True
        got = _sha256_file(path).strip().lower()
        return got == expected
    except Exception:
        return False


def _in_rollout(
    *,
    tenant_id: str | None,
    rollout_enabled: bool,
    tenant_allowlist: list[str] | None,
    canary_percent: int = 100,
) -> bool:
    if not rollout_enabled:
        return False
    t = str(tenant_id or "").strip()
    allow = [str(x).strip() for x in (tenant_allowlist or []) if str(x).strip()]
    if allow:
        return t in set(allow)
    pct = max(0, min(100, int(canary_percent or 0)))
    if pct >= 100:
        return True
    if pct <= 0:
        return False
    bucket = int(hashlib.sha256((t or "global").encode("utf-8")).hexdigest()[:8], 16) % 100
    return bucket < pct


def weighted_score(
    *,
    features: Dict[str, float],
    weights: Dict[str, float],
    bias: float = 0.0,
) -> float:
    num = float(bias or 0.0)
    den = 0.0
    for k, w in (weights or {}).items():
        try:
            v = float((features or {}).get(k) or 0.0)
            ww = float(w or 0.0)
        except Exception:
            continue
        num += (v * ww)
        den += abs(ww)
    if den <= 0:
        return _clamp01(num)
    return _clamp01(num / den)


def score_with_learned_model(
    *,
    domain: str,
    features: Dict[str, float],
    tenant_id: str | None,
    fallback_weights: Dict[str, float],
    fallback_bias: float = 0.0,
    rollout_enabled: bool = True,
    tenant_allowlist: list[str] | None = None,
    canary_percent: int = 100,
) -> Dict[str, Any]:
    rollout_active = _in_rollout(
        tenant_id=tenant_id,
        rollout_enabled=rollout_enabled,
        tenant_allowlist=tenant_allowlist,
        canary_percent=canary_percent,
    )
    artifact = load_model_artifact()
    domain_cfg = _select_domain_cfg(artifact, domain)
    model = _coerce_json_obj(domain_cfg.get("model"))
    coefficients = _coerce_json_obj(model.get("coefficients"))
    bias = float(model.get("bias", 0.0) or 0.0)

    raw_score = weighted_score(features=features, weights=fallback_weights, bias=fallback_bias)
    model_source = "static_weighted_fallback"
    feature_coverage = 0.0

    if rollout_active and str(model.get("kind") or "").lower() == "logistic" and coefficients:
        dot = bias
        used = 0
        for k, w in coefficients.items():
            try:
                v = float((features or {}).get(str(k), 0.0) or 0.0)
                ww = float(w or 0.0)
            except Exception:
                continue
            if str(k) in (features or {}):
                used += 1
            dot += (v * ww)
        raw_score = _clamp01(_sigmoid(dot))
        model_source = "learned_logistic"
        feature_coverage = round(float(used) / float(max(1, len(coefficients))), 4)

    cal_score, cal_source = _resolve_calibration(raw_score=raw_score, domain_cfg=domain_cfg, tenant_id=tenant_id)
    return {
        "raw_score": round(float(raw_score), 6),
        "calibrated_score": round(float(cal_score), 6) if cal_score is not None else None,
        "model_source": model_source,
        "calibration_source": cal_source,
        "feature_coverage": feature_coverage,
        "artifact_version": str((artifact or {}).get("version") or ""),
        "rollout_active": rollout_active,
    }


def gate_decision(
    *,
    domain: str,
    raw_score: float,
    allow_threshold: float = 0.35,
    block_threshold: float = 0.7,
    calibration_agent: str | None = None,
    precalibrated_score: float | None = None,
    metadata: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """Shared calibrated allow/review/block decision gate."""
    raw = _clamp01(float(raw_score))
    agent = calibration_agent or domain or "default"
    if precalibrated_score is not None:
        cal = _clamp01(float(precalibrated_score))
    else:
        cal = _clamp01(calibrate_confidence(raw, agent_type=agent))
    allow_thr = _clamp01(float(allow_threshold))
    block_thr = _clamp01(float(block_threshold))
    if allow_thr > block_thr:
        allow_thr, block_thr = block_thr, allow_thr

    decision = "review"
    if cal <= allow_thr:
        decision = "allow"
    elif cal >= block_thr:
        decision = "block"

    confidence = max(0.05, min(0.99, 1.0 - abs((cal - 0.5) * 2.0)))
    uncertainty = max(0.0, min(1.0, 1.0 - confidence))
    return {
        "domain": domain,
        "decision": decision,
        "raw_score": round(raw, 4),
        "calibrated_score": round(cal, 4),
        "thresholds": {
            "allow": round(allow_thr, 4),
            "block": round(block_thr, 4),
        },
        "confidence": round(confidence, 4),
        "uncertainty": round(uncertainty, 4),
        "metadata": metadata or {},
    }
