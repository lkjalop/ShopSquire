from __future__ import annotations

import json
import math
import os
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

from src.app.models.db import db_session


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        return dict(json.loads(path.read_text(encoding="utf-8")) or {})
    except Exception:
        return {}


def load_fusion_feature_config() -> Dict[str, Any]:
    p = Path(os.getenv("FUSION_FEATURES_PATH", "config/ml/fusion_features.json")).resolve()
    return _read_json(p) if p.exists() else {}


def load_calibration_params() -> Dict[str, Any]:
    p = Path(os.getenv("CALIBRATION_PARAMS_PATH", "config/ml/calibration_params.json")).resolve()
    return _read_json(p) if p.exists() else {}


def _sigmoid(x: float) -> float:
    try:
        return 1.0 / (1.0 + math.exp(-x))
    except Exception:
        return 0.5


def extract_features(
    *,
    evidence_pkg: Dict[str, Any],
    tier0_details: Optional[Dict[str, Any]] = None,
    customer_trust_score: Optional[float] = None,
) -> Dict[str, Any]:
    cv_fields = ((evidence_pkg.get("cv") or {}).get("fields") or {}) if isinstance(evidence_pkg.get("cv"), dict) else {}
    fraud_signals = evidence_pkg.get("fraud_signals") or []

    image_quality_score = None
    try:
        if isinstance(tier0_details, dict):
            iq = tier0_details.get("image_quality") or {}
            if isinstance(iq, dict) and iq.get("score") is not None:
                image_quality_score = float(iq.get("score"))
    except Exception:
        image_quality_score = None

    phash_reuse = False
    try:
        if isinstance(tier0_details, dict):
            hr = tier0_details.get("hash_reuse") or {}
            if isinstance(hr, dict) and bool(hr.get("any_reused")):
                phash_reuse = True
    except Exception:
        pass
    if not phash_reuse:
        try:
            for s in fraud_signals or []:
                if isinstance(s, dict) and s.get("type") == "image_reuse":
                    phash_reuse = True
                    break
        except Exception:
            pass

    ocr_has_serial = bool(cv_fields.get("serial"))
    ocr_has_order_id = bool(cv_fields.get("order_id"))

    trust = None
    if customer_trust_score is not None:
        try:
            trust = float(customer_trust_score)
        except Exception:
            trust = None
    if trust is None:
        # Conservative default when trust isn't available yet.
        trust = 0.5

    return {
        "image_quality_score": image_quality_score,
        "phash_reuse": bool(phash_reuse),
        "ocr_has_serial": bool(ocr_has_serial),
        "ocr_has_order_id": bool(ocr_has_order_id),
        "customer_trust_score": float(trust),
    }


def score_features(features: Dict[str, Any]) -> float:
    """Return a calibrated risk score on a 0..100 scale.

    This is an MVP placeholder for Phase 2 fusion: a stable, explainable
    baseline that can be replaced by trained models later.
    """
    iq = features.get("image_quality_score")
    try:
        iqf = float(iq) if iq is not None else 0.6
    except Exception:
        iqf = 0.6

    try:
        phash = 1.0 if bool(features.get("phash_reuse")) else 0.0
    except Exception:
        phash = 0.0
    try:
        has_serial = 1.0 if bool(features.get("ocr_has_serial")) else 0.0
    except Exception:
        has_serial = 0.0
    try:
        has_order_id = 1.0 if bool(features.get("ocr_has_order_id")) else 0.0
    except Exception:
        has_order_id = 0.0
    try:
        trust = float(features.get("customer_trust_score") or 0.5)
    except Exception:
        trust = 0.5
    trust = min(1.0, max(0.0, trust))

    # A simple, monotonic "risk" heuristic in 0..1.
    risk = 0.0
    risk += (1.0 - min(1.0, max(0.0, iqf))) * 0.30
    risk += phash * 0.40
    risk += (1.0 - has_serial) * 0.15
    risk += (1.0 - has_order_id) * 0.05
    risk += (1.0 - trust) * 0.10
    risk = min(1.0, max(0.0, risk))

    # Platt-style calibration (config-driven).
    cal = load_calibration_params()
    a = 1.0
    b = 0.0
    try:
        params = cal.get("params") if isinstance(cal.get("params"), dict) else {}
        a = float(params.get("a") or 1.0)
        b = float(params.get("b") or 0.0)
    except Exception:
        a = 1.0
        b = 0.0

    # Center risk into roughly (-1..1) before sigmoid.
    z = a * ((risk * 2.0) - 1.0) + b
    calibrated = _sigmoid(z)
    return float(calibrated * 100.0)


def persist_fusion_score(
    *,
    tenant_id: str | None,
    case_id: str | None,
    features: Dict[str, Any],
    score: float,
    source: str = "returns",
    model_version: str | None = "fusion_v0",
) -> str | None:
    fid = f"fs-{uuid.uuid4().hex}"
    try:
        with db_session() as db:
            db.execute(
                """
                INSERT INTO fusion_scores (id, tenant_id, case_id, source, features_json, score, model_version, created_at)
                VALUES (:id, :tenant_id, :case_id, :source, :features_json, :score, :model_version, CURRENT_TIMESTAMP)
                """,
                {
                    "id": fid,
                    "tenant_id": tenant_id,
                    "case_id": case_id,
                    "source": source,
                    "features_json": json.dumps(features or {}, ensure_ascii=False),
                    "score": float(score),
                    "model_version": model_version,
                },
            )
            db.commit()
        return fid
    except Exception:
        return None


def compute_and_persist(
    *,
    tenant_id: str | None,
    case_id: str | None,
    evidence_pkg: Dict[str, Any],
    tier0_details: Optional[Dict[str, Any]] = None,
    customer_trust_score: Optional[float] = None,
    source: str = "returns",
    model_version: str | None = "fusion_v0",
) -> Dict[str, Any]:
    features = extract_features(
        evidence_pkg=evidence_pkg or {},
        tier0_details=tier0_details,
        customer_trust_score=customer_trust_score,
    )
    score = score_features(features)
    fusion_id = persist_fusion_score(
        tenant_id=tenant_id,
        case_id=case_id,
        features=features,
        score=score,
        source=source,
        model_version=model_version,
    )
    return {"fusion_id": fusion_id, "score": float(score), "features": features, "model_version": model_version}

