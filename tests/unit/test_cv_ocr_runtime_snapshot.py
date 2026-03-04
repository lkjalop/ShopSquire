import builtins
import types

from src.app import main as main_mod


def test_cv_ocr_runtime_snapshot_embedded_ready_without_ocr_deps(monkeypatch):
    real_import = builtins.__import__

    def _fake_import(name, *args, **kwargs):
        if name in {"pytesseract", "cv2", "paddleocr", "pyzbar"}:
            raise ImportError(f"{name} unavailable")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _fake_import)
    snap = main_mod._cv_ocr_runtime_snapshot("embedded")
    assert snap.get("provider") == "embedded"
    assert snap.get("ready") is True


def test_cv_ocr_runtime_snapshot_tesseract_requires_binary(monkeypatch):
    real_import = builtins.__import__

    def _fake_import(name, *args, **kwargs):
        if name == "pytesseract":
            return types.ModuleType("pytesseract")
        if name in {"cv2", "paddleocr", "pyzbar"}:
            raise ImportError(f"{name} unavailable")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _fake_import)
    monkeypatch.setattr(main_mod.shutil, "which", lambda cmd: None)
    snap = main_mod._cv_ocr_runtime_snapshot("tesseract")
    assert snap.get("provider") == "tesseract"
    assert snap.get("ready") is False
    reasons = snap.get("reasons") or []
    assert "tesseract_binary_missing" in reasons
    assert "tesseract_provider_not_ready" in reasons
