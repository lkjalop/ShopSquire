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


def test_glm_ocr_snapshot_never_attempts_heavy_ocr_imports(monkeypatch):
    """Boot-path guard: paddleocr import loads the whole Paddle framework (~10-15s
    when its model source is blocked). A provider that runs via Ollama must not
    even ATTEMPT it — 'not probed' is absent from deps, never False."""
    real_import = builtins.__import__
    attempted: list[str] = []

    def _spy_import(name, *args, **kwargs):
        root = str(name).split(".")[0]
        if root in {"pytesseract", "cv2", "paddleocr", "pyzbar"}:
            attempted.append(root)
            raise ImportError(f"{root} unavailable")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _spy_import)
    snap = main_mod._cv_ocr_runtime_snapshot("glm-ocr")
    assert snap.get("ready") is True
    assert "paddleocr" not in attempted
    assert "cv2" not in attempted
    assert "pytesseract" not in attempted
    assert "paddleocr" not in (snap.get("deps") or {})  # absent = not probed, not False


def test_auto_snapshot_skips_paddle_when_tesseract_leg_ready(monkeypatch):
    """auto pays the paddle import only when the cheap tesseract leg cannot serve."""
    real_import = builtins.__import__
    attempted: list[str] = []

    def _spy_import(name, *args, **kwargs):
        root = str(name).split(".")[0]
        if root in {"pytesseract", "cv2", "paddleocr", "pyzbar"}:
            attempted.append(root)
            if root == "pytesseract":
                return types.ModuleType("pytesseract")
            raise ImportError(f"{root} unavailable")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _spy_import)
    monkeypatch.setattr(main_mod.shutil, "which", lambda cmd: "C:/fake/tesseract.exe")
    snap = main_mod._cv_ocr_runtime_snapshot("auto")
    assert snap.get("ready") is True
    assert "paddleocr" not in attempted


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
