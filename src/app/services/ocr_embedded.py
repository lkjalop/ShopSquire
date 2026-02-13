from __future__ import annotations

from io import BytesIO
from typing import Optional


def extract_embedded_text(image_bytes: bytes) -> str:
    """Best-effort "OCR" for test fixtures via PNG embedded text.

    This is intentionally simple and dependency-light so tests can assert OCR-driven
    behavior even when a system Tesseract binary is unavailable.
    """
    try:
        from PIL import Image  # type: ignore
    except Exception:
        return ""
    try:
        img = Image.open(BytesIO(image_bytes))
    except Exception:
        return ""

    # PNG tEXt/iTXt chunks are surfaced by PIL in `info`.
    try:
        info = getattr(img, "info", {}) or {}
        for key in ("shopsquire_text", "shopsquire_ocr", "Comment", "Description"):
            val = info.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
    except Exception:
        return ""
    return ""

