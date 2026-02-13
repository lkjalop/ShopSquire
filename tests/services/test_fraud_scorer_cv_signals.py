"""Tests for CV pre-LLM signals in FraudScorer."""

from src.app.services.fraud_scorer import FraudScorer


def test_pre_llm_cv_checks():
    scorer = FraudScorer()
    image_data = {
        "blur_score": 0.2,
        "histogram_anomaly": True,
        "exif": None,
        "expected_exif": True,
        "photo_timestamp": 1600000000,
        "order_timestamp": 1600001000,
        "phash_duplicate": True,
        "rapid_submission": True,
    }
    signals = scorer.pre_llm_cv_check(image_data)
    assert isinstance(signals, dict)
    assert signals.get("cv_blur_score_low") is True
    assert signals.get("cv_histogram_anomaly") is True
    assert signals.get("cv_metadata_stripped") is True
    assert signals.get("cv_timestamp_impossible") is True
    assert signals.get("cv_duplicate_hash") is True
    assert signals.get("rapid_photo_submission") is True
