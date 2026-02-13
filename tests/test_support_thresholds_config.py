import json

from src.app.routers.support_complaints import _build_evidence_tags, _evaluate_cv_rules


def _read_flags() -> dict:
    with open("config/feature_flags.json", "r", encoding="utf-8") as f:
        return json.load(f)


def _write_flags(flags: dict) -> None:
    with open("config/feature_flags.json", "w", encoding="utf-8") as f:
        json.dump(flags, f, ensure_ascii=False, indent=2)


def test_support_thresholds_drive_low_confidence_and_excessive_returns_rules():
    flags = _read_flags()
    flags["SUPPORT_THRESHOLDS"] = {
        "cv_confidence_low_min": 0.9,
        "manipulation_score_high_min": 0.7,
        "excessive_returns_last_30_days_min": 5,
        "auto_process_confidence_min_signed_in": 0.8,
        "auto_process_confidence_min_guest": 0.85,
        "auto_process_fraud_levels": ["minimal", "low"],
    }
    _write_flags(flags)

    out = _evaluate_cv_rules(
        description="box arrived damaged",
        issue_type="return",
        analysis={"confidence": 0.85, "severity": "minor"},
        extracted_text="",
        labels=["damage"],
        reverse_hits=[],
        fraud_score=None,
        fraud_level=None,
        trust={"returns_last_30_days": 4},
        order_id=None,
    )
    rule_ids = {r.get("id") for r in (out.get("rules") or [])}
    assert "CV05" in rule_ids  # low confidence should trigger when threshold is 0.9
    assert "CV31" not in rule_ids  # returns_last_30_days=4 below threshold=5


def test_support_thresholds_drive_manipulation_tagging():
    flags = _read_flags()
    flags["SUPPORT_THRESHOLDS"] = {
        "cv_confidence_low_min": 0.5,
        "manipulation_score_high_min": 0.7,
        "excessive_returns_last_30_days_min": 3,
        "auto_process_confidence_min_signed_in": 0.8,
        "auto_process_confidence_min_guest": 0.85,
        "auto_process_fraud_levels": ["minimal", "low"],
    }
    _write_flags(flags)

    tags = _build_evidence_tags(
        rule_signals={},
        forensics={"manipulation_score": 0.65},
        fraud_level=None,
        supplier_signals={},
        tier2=None,
        expected_serial=None,
        observed_serial=None,
    )
    assert "manipulation_detected" not in tags

