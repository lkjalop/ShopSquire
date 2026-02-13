from src.app.services.cv_damage_classifier import DamageClassifier


def test_damage_classifier_returns_damage_and_severity_without_models():
    clf = DamageClassifier(model_path=None, yolo_model_path=None)
    # Not a real image; classifier should still return a stable fallback payload.
    out = clf.classify(b"not-a-real-image")
    assert isinstance(out, dict)
    assert out.get("damage_type") is not None
    assert out.get("severity") is not None
    assert "confidence" in out
    assert out.get("status") in ("heuristic_no_detection", "heuristic_predicted", "model_predicted")
