from __future__ import annotations

import os
import time
from typing import Any, Dict

from src.app.services.cv_object_detector import CVObjectDetector
from src.app.services.cv_quality import score_quality
from src.app.services.cv_ocr import extract_text
from src.app.services.cv_model_pack import get_model_pack


def _tiny_image_bytes() -> bytes:
    # 1x1 PNG to keep OCR/CLIP/YOLO lightweight.
    return (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\nIDATx\xdac``\x00\x00"
        b"\x00\x04\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    )


def warmup_cv_models(pack_id: str | None = None) -> Dict[str, Any]:
    """Preload CV dependencies and return readiness signals.

    Intended for demo warmups to avoid first-call latency.
    """
    started = time.time()
    image_bytes = _tiny_image_bytes()
    pack = get_model_pack(pack_id)
    detector_cfg = (pack.get("detector") or {}) if isinstance(pack.get("detector"), dict) else {}
    ocr_cfg = (pack.get("ocr") or {}) if isinstance(pack.get("ocr"), dict) else {}
    quality_cfg = (pack.get("quality") or {}) if isinstance(pack.get("quality"), dict) else {}

    out: Dict[str, Any] = {"model_pack": pack.get("id")}

    # YOLO warmup
    try:
        model_path = detector_cfg.get("model")
        det = CVObjectDetector(model_path=model_path)
        _ = det.detect(image_bytes)
        out["yolo_ready"] = True
    except Exception as exc:
        out["yolo_ready"] = False
        out["yolo_error"] = str(exc)

    # OCR warmup
    try:
        _ = extract_text(image_bytes, provider=ocr_cfg.get("provider"), fallback=ocr_cfg.get("fallback"))
        out["ocr_ready"] = True
        out["ocr_provider"] = ocr_cfg.get("provider") or "auto"
    except Exception as exc:
        out["ocr_ready"] = False
        out["ocr_error"] = str(exc)

    # CLIP quality warmup
    try:
        labels = quality_cfg.get("labels") if isinstance(quality_cfg.get("labels"), list) else []
        if labels:
            _ = score_quality(image_bytes, labels[:2])
        out["clip_ready"] = True
    except Exception as exc:
        out["clip_ready"] = False
        out["clip_error"] = str(exc)

    out["elapsed_ms"] = int((time.time() - started) * 1000)
    out["warmup_on_start"] = os.getenv("CV_WARMUP_ON_START", "").lower() in ("1", "true", "yes")
    return out
