"""Bound the cost of the VLM/OCR pass on uploaded images.

The vision triage pipeline runs a VLM + OCR on the raw upload. On a 2-24 MP image
(normal e-commerce photo sizes) that hangs the model for minutes — a trivial DoS and a
functional gap. The ingest gate caps *bytes* but not decoded *pixels*, so a small-but-huge
image (heavy compression, enormous dimensions) slips through.

This module reads the dimensions from the image header CHEAPLY (PIL reads size lazily,
without a full decode), rejects decode-bombs, and returns a DOWNSCALED COPY for the model
pass. The caller keeps the full-resolution original for steg / forensic LSB analysis (which
is fast and MUST see the untouched pixels).

Design: time is the *budget*, size is the *gate* — you can't know processing time upfront,
but you can read megapixels from the header in <1 ms. Thresholds are calibrated so "large"
means "won't finish in the budget."
"""
from __future__ import annotations

import io
import os
from typing import Any, Dict, Optional


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)) or default)
    except Exception:
        return default


# Downscale the VLM/OCR copy to this longest edge (≈1 MP for 4:3 — the Qwen-VL comfort zone,
# keeps on-screen text legible while bounding vision tokens).
VLM_MAX_EDGE_PX = _int_env("CV_VLM_MAX_EDGE_PX", 1280)
# Only bother downscaling above this (small images pass through untouched).
DOWNSCALE_ABOVE_EDGE_PX = _int_env("CV_DOWNSCALE_ABOVE_EDGE_PX", 1536)
# Hard reject: absurd for a product photo, likely a decode-bomb / abuse.
MAX_MEGAPIXELS = _int_env("CV_IMAGE_MAX_MEGAPIXELS", 30)
MAX_BYTES = _int_env("CV_IMAGE_MAX_BYTES", 25 * 1024 * 1024)
# Warn-and-consent band (advisory; the caller decides whether to prompt the user).
WARN_MEGAPIXELS = _int_env("CV_IMAGE_WARN_MEGAPIXELS", 10)
WARN_BYTES = _int_env("CV_IMAGE_WARN_BYTES", 8 * 1024 * 1024)


def probe_image(blob: bytes) -> Dict[str, Any]:
    """Read dimensions from the header without a full decode. Cheap (<1 ms).

    Returns {width, height, megapixels, bytes, readable}. `readable=False` when the format
    can't be introspected (caller should fall back to a byte-size backstop)."""
    n = len(blob or b"")
    try:
        from PIL import Image  # lazy import; Pillow is already a dep of the CV path
        with Image.open(io.BytesIO(blob)) as im:
            w, h = im.size
        mp = round((w * h) / 1_000_000, 3)
        return {"width": int(w), "height": int(h), "megapixels": mp, "bytes": n, "readable": True}
    except Exception:
        return {"width": None, "height": None, "megapixels": None, "bytes": n, "readable": False}


def size_class(blob: bytes) -> Dict[str, Any]:
    """Classify an upload for the caller's UX decision (reject / warn / ok) WITHOUT decoding
    or downscaling. Used by the chat/upload path to drive warn-and-consent messaging."""
    p = probe_image(blob)
    mp, n = p.get("megapixels"), p.get("bytes") or 0
    reject = bool(n > MAX_BYTES or (mp is not None and mp > MAX_MEGAPIXELS))
    warn = bool(not reject and (n > WARN_BYTES or (mp is not None and mp > WARN_MEGAPIXELS)))
    reason = None
    if reject:
        reason = "bytes" if n > MAX_BYTES else "megapixels"
    return {**p, "verdict": "reject" if reject else ("warn" if warn else "ok"), "reason": reason,
            "limits": {"max_megapixels": MAX_MEGAPIXELS, "max_bytes": MAX_BYTES,
                       "warn_megapixels": WARN_MEGAPIXELS, "warn_bytes": WARN_BYTES}}


def bound_image_for_vlm(blob: bytes, *, max_edge: Optional[int] = None) -> Dict[str, Any]:
    """Return a copy of `blob` safe to feed the VLM/OCR.

    Result:
      {"reject": True,  "reason": "megapixels"|"bytes"|"decode"|"resize", "meta": {...}}
      {"reject": False, "bytes": <downscaled-or-original>, "downscaled": bool, "meta": {...}}

    On any decode error the original bytes pass through (best-effort; the CV timeout is the
    backstop) EXCEPT when the raw byte size alone exceeds MAX_BYTES, which is always rejected.
    NEVER mutates the input; the caller must keep the original for steg/forensics.
    """
    edge = int(max_edge or VLM_MAX_EDGE_PX)
    p = probe_image(blob)
    n = p.get("bytes") or 0
    mp = p.get("megapixels")

    # Hard reject (decode-bomb / abuse). Byte cap applies even when dimensions are unreadable.
    if n > MAX_BYTES:
        return {"reject": True, "reason": "bytes", "meta": p}
    if mp is not None and mp > MAX_MEGAPIXELS:
        return {"reject": True, "reason": "megapixels", "meta": p}

    w, h = p.get("width"), p.get("height")
    if not p.get("readable") or not w or not h:
        # Can't introspect — pass through; CV_VISION_TIMEOUT_SEC bounds the model call.
        return {"reject": True, "reason": "decode", "meta": p}

    if max(w, h) <= max(edge, DOWNSCALE_ABOVE_EDGE_PX):
        return {"reject": False, "bytes": blob, "downscaled": False, "meta": p}

    # Downscale a COPY for the model. Full-res original stays with the caller for steg.
    try:
        from PIL import Image
        with Image.open(io.BytesIO(blob)) as im:
            im = im.convert("RGB")
            im.thumbnail((edge, edge), Image.LANCZOS)
            buf = io.BytesIO()
            im.save(buf, format="JPEG", quality=90)
            out = buf.getvalue()
        meta = {**p, "downscaled_to": list(im.size), "downscaled_bytes": len(out), "max_edge": edge}
        return {"reject": False, "bytes": out, "downscaled": True, "meta": meta}
    except Exception:
        # Downscale failed (odd format) — pass original through; timeout backstops it.
        return {"reject": True, "reason": "resize", "meta": p}
