from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple


try:
    from PIL import Image, ImageFilter, ImageStat  # type: ignore
    from io import BytesIO
except Exception:  # pragma: no cover
    Image = None  # type: ignore
    BytesIO = None  # type: ignore


ALLOWED_MIME = {"image/jpeg", "image/jpg", "image/png", "image/webp"}


@dataclass
class ImageQualityResult:
    ok: bool
    score: float
    reasons: List[str]
    details: Dict[str, Any]


def sniff_format(image_bytes: bytes) -> str | None:
    b = image_bytes or b""
    if b.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if b.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if b[:12].startswith(b"RIFF") and b[8:12] == b"WEBP":
        return "webp"
    return None


def _blur_score_pillow(image_bytes: bytes) -> float | None:
    # A cheap, dependency-light blur proxy: edge energy.
    if Image is None or BytesIO is None:
        return None
    try:
        img = Image.open(BytesIO(image_bytes)).convert("L")
        edges = img.filter(ImageFilter.FIND_EDGES)
        stat = ImageStat.Stat(edges)
        mean = float(stat.mean[0])
        # Normalize: edge mean ~ [0..255]. Higher => sharper.
        return max(0.0, min(1.0, mean / 64.0))
    except Exception:
        return None


def assess_image_quality(
    images: List[Tuple[str, bytes]],
    *,
    min_bytes: int = 8_000,
    min_dim: int = 128,
    min_quality_score: float = 0.6,
) -> ImageQualityResult:
    reasons: List[str] = []
    details: Dict[str, Any] = {"images": []}

    if not images:
        return ImageQualityResult(ok=False, score=0.0, reasons=["no_images"], details=details)

    scores: List[float] = []
    for fname, b in images:
        r: List[str] = []
        fmt = sniff_format(b)
        if fmt is None:
            r.append("unknown_format")
        if len(b or b"") < min_bytes:
            r.append("too_small_bytes")

        w = h = None
        if Image is not None and BytesIO is not None:
            try:
                im = Image.open(BytesIO(b))
                w, h = im.size
                if min(w, h) < min_dim:
                    r.append("too_small_dim")
            except Exception:
                r.append("cannot_decode")
        blur = _blur_score_pillow(b)
        if blur is not None and blur < 0.35:
            r.append("blurry")

        # A simple per-image score: start at 1.0, subtract penalties.
        s = 1.0
        if "unknown_format" in r:
            s -= 0.5
        if "cannot_decode" in r:
            s -= 0.7
        if "too_small_bytes" in r:
            s -= 0.3
        if "too_small_dim" in r:
            s -= 0.3
        if "blurry" in r:
            s -= 0.25
        s = max(0.0, min(1.0, s))
        scores.append(s)

        details["images"].append(
            {
                "filename": fname,
                "format": fmt,
                "bytes": len(b or b""),
                "width": w,
                "height": h,
                "blur_score": blur,
                "reasons": r,
                "score": s,
            }
        )
        reasons.extend(r)

    # Overall is min score across images (conservative).
    overall = min(scores) if scores else 0.0
    ok = overall >= float(min_quality_score)
    return ImageQualityResult(ok=ok, score=overall, reasons=sorted(set(reasons)), details=details)

