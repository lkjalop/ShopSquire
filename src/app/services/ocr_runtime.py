"""Provider-scoped OCR availability without importing the inference framework."""
import importlib.util
import os
import shutil
import subprocess
from typing import Any

from src.app.services.paddle_model_assets import local_paddle_models, PaddleAssetError


def ocr_runtime_snapshot(provider: str | None = None) -> dict[str, Any]:
    """Report the selected local provider's package, binary and asset prerequisites.

    Package discovery uses metadata. Native inference remains in its bounded
    worker; probing availability must not start model downloads or a framework.
    """
    selected = (provider or os.getenv("CV_OCR_PROVIDER", "auto") or "auto").strip().lower()
    no_local_ocr = selected in ("disabled", "none", "off", "embedded", "glm-ocr", "glm_ocr", "ollama-ocr")

    def _probe(*pkgs: str) -> None:
        for pkg in pkgs:
            try:
                deps[pkg] = importlib.util.find_spec(pkg) is not None
            except Exception:
                deps[pkg] = False

    deps: dict[str, bool] = {}
    _probe("pyzbar")  # QR-decode runtime is provider-independent and cheap
    if selected == "tesseract":
        _probe("pytesseract")
    elif not no_local_ocr and selected != "paddle":  # auto: probe the cheap leg now; paddle only if it's needed (below)
        _probe("pytesseract")

    runtime: dict[str, Any] = {}
    reasons: list[str] = []

    def paddle_ready():
        _probe("paddleocr", "paddle", "cv2")
        if not all(deps.get(name) for name in ("paddleocr", "paddle", "cv2")):
            runtime["paddle_model_assets"] = False
            reasons.append("paddle_dependencies_missing")
            return False
        try:
            local_paddle_models()
            runtime["paddle_model_assets"] = True
            return True
        except PaddleAssetError as exc:
            runtime["paddle_model_assets"] = False
            reasons.append(str(exc))
            return False

    # pytesseract requires a working runtime binary as well as its package.
    tess_path = shutil.which("tesseract")
    runtime["tesseract_path"] = tess_path
    runtime["tesseract_bin"] = bool(tess_path)
    if deps.get("pytesseract") and tess_path:
        try:
            proc = subprocess.run([tess_path, "--version"], capture_output=True, text=True, timeout=2)
            runtime["tesseract_version_ok"] = proc.returncode == 0
            if proc.returncode != 0:
                reasons.append("tesseract_version_probe_failed")
        except Exception:
            runtime["tesseract_version_ok"] = False
            reasons.append("tesseract_version_probe_failed")
    elif deps.get("pytesseract") and not tess_path:
        reasons.append("tesseract_binary_missing")

    # pyzbar requires libzbar runtime.
    if deps.get("pyzbar"):
        try:
            from pyzbar.pyzbar import decode as _decode  # type: ignore

            runtime["pyzbar_runtime"] = bool(_decode)
        except Exception:
            runtime["pyzbar_runtime"] = False
            reasons.append("pyzbar_runtime_missing")
    else:
        runtime["pyzbar_runtime"] = False

    if no_local_ocr:
        ready = True  # glm-ocr uses Ollama — no local binary required
    elif selected == "tesseract":
        ready = bool(deps.get("pytesseract") and runtime.get("tesseract_bin") and runtime.get("tesseract_version_ok"))
        if not ready:
            reasons.append("tesseract_provider_not_ready")
    elif selected == "paddle":
        ready = paddle_ready()
        if not ready:
            reasons.append("paddle_provider_not_ready")
    else:
        # auto: the cheap tesseract leg was probed above; check Paddle metadata
        # only when that leg cannot serve. The framework itself remains in its worker.
        ready = bool(deps.get("pytesseract") and runtime.get("tesseract_bin") and runtime.get("tesseract_version_ok"))
        if not ready:
            ready = paddle_ready()
        if not ready:
            reasons.append("no_available_ocr_provider")

    return {
        "provider": selected,
        "ready": bool(ready),
        "deps": deps,
        "runtime": runtime,
        "reasons": list(dict.fromkeys([str(r) for r in reasons if str(r)])),
    }
