import sys
from types import SimpleNamespace
from src.app.services.cv_damage_classifier import DamageClassifier


def test_missing_detector_weights_do_not_invoke_download_capable_constructor(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setitem(sys.modules, 'ultralytics', SimpleNamespace(YOLO=lambda path: calls.append(path)))
    detector = DamageClassifier(yolo_model_path=str(tmp_path / 'missing.pt'))
    assert calls == []
    assert detector.detect_objects(b'not-an-image') == []


def test_explicit_local_weights_can_be_loaded(monkeypatch, tmp_path):
    path = tmp_path / 'enrolled.pt'; path.write_bytes(b'fixture')
    model = object(); calls = []
    def load(value):
        calls.append(value)
        return model
    monkeypatch.setitem(sys.modules, 'ultralytics', SimpleNamespace(YOLO=load))
    assert DamageClassifier(yolo_model_path=str(path)).yolo is model
    assert calls == [str(path)]
