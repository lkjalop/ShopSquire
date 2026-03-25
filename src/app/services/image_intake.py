from __future__ import annotations

import hashlib
import imghdr
from typing import Any, Dict, Optional


def _strip_exif(image_bytes: bytes) -> bytes:
    """Attempt to remove EXIF metadata. Falls back to original bytes if Pillow is unavailable."""
    try:
        from PIL import Image
        import io
        img = Image.open(io.BytesIO(image_bytes))
        # Re-save without EXIF
        out = io.BytesIO()
        img.save(out, format=img.format or "JPEG")
        return out.getvalue()
    except Exception:
        return image_bytes


def _perceptual_hash(image_bytes: bytes) -> Optional[str]:
    """Compute a perceptual hash if PIL/imagehash are available; else None."""
    try:
        from PIL import Image
        import imagehash  # type: ignore
        import io
        img = Image.open(io.BytesIO(image_bytes))
        return str(imagehash.phash(img))
    except Exception:
        return None


def sanitize_image(image_bytes: bytes, max_bytes: int = 10 * 1024 * 1024) -> Dict[str, Any]:
    """Preflight checks and sanitization for uploaded images.

    - Validate MIME via imghdr
    - Size limit
    - Strip EXIF (best-effort)
    - Compute SHA256 and optional perceptual hash
    """
    if not image_bytes:
        return {"status": "invalid", "reason": "empty"}

    if len(image_bytes) > max_bytes:
        return {"status": "invalid", "reason": "too_large", "size": len(image_bytes)}

    kind = imghdr.what(None, h=image_bytes)
    if kind is None:
        try:
            from PIL import Image
            import io

            with Image.open(io.BytesIO(image_bytes)) as img:
                fmt = str(img.format or "").strip().lower()
            if fmt == "avif":
                kind = "avif"
        except Exception:
            kind = None
    if kind not in {"jpeg", "png", "bmp", "gif", "tiff"}:
        # Accept unknown but flag for review
        mime = f"unknown:{kind}" if kind else "unknown"
    else:
        mime = f"image/{kind}"
    if kind == "avif":
        mime = "image/avif"

    stripped = _strip_exif(image_bytes)
    sha256 = hashlib.sha256(stripped).hexdigest()
    phash = _perceptual_hash(stripped)

    return {
        "status": "sanitized",
        "mime": mime,
        "size": len(stripped),
        "sha256": sha256,
        "phash": phash,
        "bytes": stripped,
    }
