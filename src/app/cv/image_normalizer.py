from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from typing import Any, Dict, Tuple


@dataclass(frozen=True)
class NormalizedImage:
    image_bytes: bytes
    meta: Dict[str, Any]


def normalize_image_bytes(
    image_bytes: bytes,
    *,
    max_dim: int = 1280,
) -> NormalizedImage:
    """Normalize user-uploaded images for CV stages.

    Goals:
    - deterministic byte representation (PNG)
    - orientation-correct (EXIF transpose when available)
    - bounded dimensions (reduce huge images)

    If Pillow is unavailable or image decode fails, returns input bytes unchanged.
    """
    if not image_bytes:
        return NormalizedImage(image_bytes=b"", meta={"ok": False, "reason": "empty"})

    try:
        from PIL import Image, ImageOps  # type: ignore
    except Exception:
        return NormalizedImage(image_bytes=image_bytes, meta={"ok": False, "reason": "pillow_missing"})

    try:
        img = Image.open(BytesIO(image_bytes))
        img = ImageOps.exif_transpose(img)
        img = img.convert("RGB")
    except Exception:
        return NormalizedImage(image_bytes=image_bytes, meta={"ok": False, "reason": "decode_failed"})

    w, h = img.size
    new_w, new_h = w, h
    try:
        if max(w, h) > int(max_dim):
            scale = float(max_dim) / float(max(w, h))
            new_w = max(1, int(round(w * scale)))
            new_h = max(1, int(round(h * scale)))
            img = img.resize((new_w, new_h))
    except Exception:
        new_w, new_h = w, h

    buf = BytesIO()
    try:
        img.save(buf, format="PNG", optimize=True)
        out = buf.getvalue()
    except Exception:
        out = image_bytes

    return NormalizedImage(
        image_bytes=out,
        meta={
            "ok": True,
            "format": "png",
            "original_width": w,
            "original_height": h,
            "width": new_w,
            "height": new_h,
            "original_size_bytes": len(image_bytes),
            "size_bytes": len(out),
            "resized": (new_w, new_h) != (w, h),
        },
    )

