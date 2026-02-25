from __future__ import annotations

import random

from src.app.services.ml_decision_gate import _load_model_artifact, gate_decision, score_with_learned_model
from src.app.services.ml_decision_gate_training import GateTrainingSample, save_gate_artifact, train_gate_from_samples


def test_train_gate_from_samples_learns_coeffs_and_tenant_calibration():
    rnd = random.Random(9)
    rows = []
    for i in range(100):
        tenant = "t1" if i < 60 else "t2"
        signal = rnd.random()
        auth = 1.0 if rnd.random() < 0.35 else 0.0
        y = 1 if (0.62 * signal + 0.38 * auth) >= 0.52 else 0
        rows.append(
            GateTrainingSample(
                tenant_id=tenant,
                label=y,
                features={"signal_density": signal, "auth_fail": auth},
                decision_id=f"d{i}",
            )
        )

    out = train_gate_from_samples(rows, min_samples=20, min_tenant_samples=20)
    assert out.get("updated") is True
    artifact = out.get("artifact") or {}
    dom = ((artifact.get("domains") or {}).get("email_security") or {})
    coeffs = (((dom.get("model") or {}).get("coefficients")) or {})
    assert "signal_density" in coeffs
    assert "auth_fail" in coeffs
    tenant_cal = dom.get("tenant_calibration") or {}
    assert "t1" in tenant_cal
    assert "t2" in tenant_cal


def test_runtime_gate_uses_artifact_and_tenant_platt(tmp_path, monkeypatch):
    artifact = {
        "version": "ml_decision_gate_v1",
        "domains": {
            "email_security": {
                "model": {
                    "kind": "logistic",
                    "bias": -1.2,
                    "coefficients": {"signal_density": 1.7, "auth_fail": 1.1},
                },
                "calibration": {"method": "platt", "params": {"a": 1.0, "b": 0.0}},
                "tenant_calibration": {
                    "tenant-abc": {"method": "platt", "params": {"a": 1.8, "b": -0.25}, "sample_size": 48}
                },
            }
        },
    }
    path = tmp_path / "ml_decision_gate_model.json"
    save_gate_artifact(artifact, output_path=str(path))
    monkeypatch.setenv("ML_DECISION_GATE_MODEL_PATH", str(path))
    _load_model_artifact.cache_clear()

    score = score_with_learned_model(
        domain="email_security",
        tenant_id="tenant-abc",
        features={"signal_density": 0.9, "auth_fail": 1.0},
        fallback_weights={"signal_density": 0.2},
    )
    assert score.get("model_source") == "learned_logistic"
    assert score.get("calibration_source") == "tenant_platt"
    assert score.get("calibrated_score") is not None

    gate = gate_decision(
        domain="email_security",
        raw_score=float(score.get("raw_score") or 0.0),
        precalibrated_score=float(score.get("calibrated_score") or 0.0),
        allow_threshold=0.25,
        block_threshold=0.65,
        metadata={"model_source": score.get("model_source")},
    )
    assert gate.get("decision") in {"allow", "review", "block"}
    assert (gate.get("metadata") or {}).get("model_source") == "learned_logistic"


def test_trained_artifact_changes_routing_deterministically(tmp_path, monkeypatch):
    artifact = {
        "version": "ml_decision_gate_v1",
        "domains": {
            "email_security": {
                "model": {"kind": "logistic", "bias": -2.0, "coefficients": {"signal_density": 5.5}},
                "calibration": {"method": "platt", "params": {"a": 1.0, "b": 0.0}},
                "calibration_policy": {"tenant_min_samples": 10, "tenant_min_quality": 0.55},
                "tenant_calibration": {},
            }
        },
    }
    path = tmp_path / "ml_decision_gate_model.json"
    save_gate_artifact(artifact, output_path=str(path))
    monkeypatch.setenv("ML_DECISION_GATE_MODEL_PATH", str(path))
    _load_model_artifact.cache_clear()

    learned = score_with_learned_model(
        domain="email_security",
        tenant_id="tenant-live",
        features={"signal_density": 0.9},
        fallback_weights={"signal_density": 0.05},
        rollout_enabled=True,
        tenant_allowlist=["tenant-live"],
        canary_percent=100,
    )
    static = score_with_learned_model(
        domain="email_security",
        tenant_id="tenant-live",
        features={"signal_density": 0.9},
        fallback_weights={"signal_density": 0.05},
        rollout_enabled=False,
        tenant_allowlist=[],
        canary_percent=0,
    )
    g_learned = gate_decision(domain="email_security", raw_score=float(learned["raw_score"]), precalibrated_score=float(learned["calibrated_score"] or learned["raw_score"]), allow_threshold=0.2, block_threshold=0.7)
    g_static = gate_decision(domain="email_security", raw_score=float(static["raw_score"]), precalibrated_score=float(static["calibrated_score"] or static["raw_score"]), allow_threshold=0.2, block_threshold=0.7)
    assert learned.get("model_source") == "learned_logistic"
    assert static.get("model_source") == "static_weighted_fallback"
    assert abs(float(learned.get("raw_score") or 0.0) - float(static.get("raw_score") or 0.0)) >= 0.05
    assert g_learned.get("decision") in {"allow", "review", "block"}
    assert g_static.get("decision") in {"allow", "review", "block"}


def test_missing_or_corrupt_artifact_falls_back_to_static(tmp_path, monkeypatch):
    bad_path = tmp_path / "missing.json"
    monkeypatch.setenv("ML_DECISION_GATE_MODEL_PATH", str(bad_path))
    _load_model_artifact.cache_clear()
    s1 = score_with_learned_model(
        domain="email_security",
        tenant_id="t1",
        features={"signal_density": 0.8},
        fallback_weights={"signal_density": 0.3},
    )
    assert s1.get("model_source") == "static_weighted_fallback"

    artifact = {"version": "ml_decision_gate_v1", "domains": {"email_security": {"model": {"kind": "logistic", "bias": 0.0, "coefficients": {"signal_density": 1.0}}}}}
    path = tmp_path / "artifact.json"
    save_gate_artifact(artifact, output_path=str(path))
    pointer = tmp_path / "active.json"
    pointer.write_text('{"active_path":"' + str(path).replace("\\", "\\\\") + '","active_checksum_sha256":"deadbeef"}', encoding="utf-8")
    monkeypatch.setenv("ML_DECISION_GATE_ACTIVE_POINTER_PATH", str(pointer))
    _load_model_artifact.cache_clear()
    s2 = score_with_learned_model(
        domain="email_security",
        tenant_id="t2",
        features={"signal_density": 0.8},
        fallback_weights={"signal_density": 0.3},
        rollout_enabled=True,
        canary_percent=100,
    )
    assert s2.get("model_source") == "static_weighted_fallback"


def test_tenant_calibration_low_samples_reverts_to_global(tmp_path, monkeypatch):
    artifact = {
        "version": "ml_decision_gate_v1",
        "domains": {
            "email_security": {
                "model": {"kind": "logistic", "bias": 0.0, "coefficients": {"signal_density": 2.0}},
                "calibration": {"method": "platt", "params": {"a": 1.0, "b": 0.0}},
                "calibration_policy": {"tenant_min_samples": 25, "tenant_min_quality": 0.55},
                "tenant_calibration": {
                    "tenant-low": {"method": "platt", "params": {"a": 3.0, "b": -1.0}, "sample_size": 8, "quality_score": 0.91}
                },
            }
        },
    }
    path = tmp_path / "model.json"
    save_gate_artifact(artifact, output_path=str(path))
    monkeypatch.setenv("ML_DECISION_GATE_MODEL_PATH", str(path))
    _load_model_artifact.cache_clear()
    s = score_with_learned_model(
        domain="email_security",
        tenant_id="tenant-low",
        features={"signal_density": 0.6},
        fallback_weights={"signal_density": 0.2},
        rollout_enabled=True,
        canary_percent=100,
    )
    assert s.get("calibration_source") == "global_platt"
