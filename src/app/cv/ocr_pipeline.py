from __future__ import annotations

from typing import Any, Dict, Optional

from src.app.cv.ocr_postprocess import extract_fields


class OCRPipeline:
    def __init__(self, provider: str | None = None, *, patterns: Optional[Dict[str, Any]] = None):
        self.provider = provider
        self.patterns = patterns or {}

    def run(self, image_bytes: bytes) -> Dict[str, Any]:
        try:
            from src.app.services.cv_ocr import extract_text

            out = extract_text(image_bytes, provider=self.provider)
        except Exception:
            out = {"text": "", "confidence": 0.0, "boxes": [], "provider": None, "error": "ocr_failed"}
        text = out.get("text") or ""
        try:
            fields = extract_fields(text, patterns=self.patterns if isinstance(self.patterns, dict) else None)
        except Exception:
            fields = {}
        return {
            "text": text,
            "confidence": float(out.get("confidence") or 0.0),
            "boxes": out.get("boxes") or [],
            "provider": out.get("provider"),
            "error": out.get("error"),
            "degraded": bool(out.get("degraded")),
            "degradation_reason": out.get("degradation_reason"),
            "fields": fields,
        }
