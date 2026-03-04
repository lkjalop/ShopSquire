from __future__ import annotations

import os
from io import BytesIO
from typing import Any, Dict, List

from src.app.services.ocr_embedded import extract_embedded_text


def _ocr_timeout_sec() -> int | None:
    try:
        v = os.getenv("CV_OCR_TIMEOUT_SEC")
        if v is None or str(v).strip() == "":
            return None
        sec = int(float(str(v).strip()))
        if sec <= 0:
            return None
        return min(sec, 60)
    except Exception:
        return None


def _embedded_ocr(image_bytes: bytes) -> Dict[str, Any]:
    text = extract_embedded_text(image_bytes)
    if not text:
        return {"text": "", "confidence": 0.0, "boxes": [], "error": None, "provider": "embedded"}
    # Provide synthetic "boxes" so downstream heuristics (e.g., document detection)
    # can still work in tests without a heavyweight OCR engine.
    import re

    tokens = [t for t in re.findall(r"[A-Za-z0-9]+", (text or "")) if t.strip()]
    boxes = [{"text": t.strip(), "conf": 99.0, "left": 0, "top": 0, "width": 0, "height": 0} for t in tokens[:96]]
    return {"text": text[:2000], "confidence": 0.95, "boxes": boxes, "provider": "embedded"}


def _annotate_degradation(out: Dict[str, Any]) -> Dict[str, Any]:
    payload = dict(out or {})
    txt = str(payload.get("text") or "").strip()
    err = str(payload.get("error") or "").strip()
    degraded = bool((not txt) and err)
    payload["degraded"] = degraded
    payload["degradation_reason"] = err[:200] if degraded else None
    return payload


def _tesseract_ocr(image_bytes: bytes) -> Dict[str, Any]:
    try:
        from PIL import Image
        import pytesseract  # type: ignore
    except Exception as exc:
        return {"text": "", "confidence": 0.0, "boxes": [], "error": str(exc), "provider": "tesseract"}
    try:
        # Windows installs often aren't on PATH; allow explicit configuration.
        cmd = os.getenv("TESSERACT_CMD") or os.getenv("TESSERACT_PATH")
        if not cmd:
            default = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
            if os.name == "nt" and os.path.exists(default):
                cmd = default
        if cmd and os.path.exists(cmd):
            pytesseract.pytesseract.tesseract_cmd = cmd
    except Exception:
        pass
    try:
        img = Image.open(BytesIO(image_bytes))
    except Exception as exc:
        return {"text": "", "confidence": 0.0, "boxes": [], "error": str(exc), "provider": "tesseract"}
    timeout = _ocr_timeout_sec()
    text = ""
    try:
        if timeout is not None:
            text = pytesseract.image_to_string(img, timeout=timeout) or ""
        else:
            text = pytesseract.image_to_string(img) or ""
    except Exception:
        return {"text": "", "confidence": 0.0, "boxes": [], "error": "ocr_failed_or_timed_out", "provider": "tesseract"}
    boxes: List[Dict[str, Any]] = []
    try:
        if timeout is not None:
            data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT, timeout=timeout)
        else:
            data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)
        n = len(data.get("text", []))
        for i in range(n):
            if not (data.get("text", [""])[i] or "").strip():
                continue
            conf = float(data.get("conf", [0])[i])
            boxes.append(
                {
                    "text": data.get("text", [""])[i],
                    "conf": conf,
                    "left": int(data.get("left", [0])[i]),
                    "top": int(data.get("top", [0])[i]),
                    "width": int(data.get("width", [0])[i]),
                    "height": int(data.get("height", [0])[i]),
                }
            )
    except Exception:
        boxes = []
    confs = [b.get("conf") for b in boxes if isinstance(b.get("conf"), (int, float))]
    confidence = max(0.0, min(1.0, (sum(confs) / max(len(confs), 1)) / 100.0)) if confs else 0.4
    return {"text": text[:2000], "confidence": confidence, "boxes": boxes, "provider": "tesseract"}


def _paddle_ocr(image_bytes: bytes) -> Dict[str, Any]:
    try:
        from paddleocr import PaddleOCR  # type: ignore
        from PIL import Image
    except Exception as exc:
        return {"text": "", "confidence": 0.0, "boxes": [], "error": str(exc), "provider": "paddle"}
    try:
        ocr = PaddleOCR(use_angle_cls=True, lang="en")
        img = Image.open(BytesIO(image_bytes))
        res = ocr.ocr(img, cls=True)
    except Exception as exc:
        return {"text": "", "confidence": 0.0, "boxes": [], "error": str(exc), "provider": "paddle"}
    lines: List[str] = []
    boxes: List[Dict[str, Any]] = []
    confs: List[float] = []
    for line in res or []:
        for box, (text, conf) in line:
            lines.append(text)
            confs.append(float(conf))
            boxes.append({"text": text, "conf": float(conf), "box": box})
    confidence = max(0.0, min(1.0, sum(confs) / max(len(confs), 1))) if confs else 0.4
    return {"text": " ".join(lines)[:2000], "confidence": confidence, "boxes": boxes, "provider": "paddle"}


def extract_text(image_bytes: bytes, provider: str | None = None, fallback: str | None = None) -> Dict[str, Any]:
    # Allow tests/integration to override without editing model packs.
    provider = (os.getenv("CV_OCR_PROVIDER") or provider or "tesseract").lower()
    if provider in ("disabled", "none", "off"):
        return _annotate_degradation({"text": "", "confidence": 0.0, "boxes": [], "error": None, "provider": "disabled"})
    if provider == "paddle":
        out = _paddle_ocr(image_bytes)
        if out.get("text") or not fallback:
            return _annotate_degradation(out)
        return _annotate_degradation(_tesseract_ocr(image_bytes))
    if provider == "embedded":
        out = _embedded_ocr(image_bytes)
        if out.get("text") or not fallback:
            return _annotate_degradation(out)
        # If embedded text is missing, honor fallback behavior.
        return extract_text(image_bytes, provider=fallback, fallback=None)
    if provider == "tesseract":
        return _annotate_degradation(_tesseract_ocr(image_bytes))
    return _annotate_degradation(_tesseract_ocr(image_bytes))
