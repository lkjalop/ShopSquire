from __future__ import annotations

import json
import os
from functools import lru_cache

from typing import Any, Dict, List, Tuple, Optional

from src.app.cv.ocr_pipeline import OCRPipeline
from src.app.cv.roi_cropper import ROICropper
from src.app.cv.roi_detector import ROIDetector
from src.app.cv.image_normalizer import normalize_image_bytes
from src.app.policy.vertical_pack import VerticalPack


@lru_cache(maxsize=1)
def _load_cv_config() -> Dict[str, Any]:
    """Load optional CV config packs referenced by the roadmap.

    The CV/OCR pipeline must still run when these files are missing.
    """
    out: Dict[str, Any] = {}
    base = os.getenv("CV_CONFIG_DIR", "config/cv")
    for name in ("roi_classes.json", "ocr_patterns.json", "vendor_dictionaries.json"):
        p = os.path.join(base, name)
        try:
            if os.path.exists(p):
                with open(p, "r", encoding="utf-8") as f:
                    out[name] = json.load(f)
        except Exception:
            out[name] = {}
    return out


def _cap_int(env_key: str, default: int, *, lo: int = 1, hi: int = 1000) -> int:
    try:
        v = os.getenv(env_key)
        if v is None or str(v).strip() == "":
            return default
        n = int(float(str(v).strip()))
        return max(lo, min(hi, n))
    except Exception:
        return default


def run_pipeline(
    images: List[Tuple[str, bytes]],
    *,
    pack: Optional[VerticalPack] = None,
    roi_model_path: str | None = None,
    ocr_provider: str | None = None,
) -> Dict[str, Any]:
    """Run ROI→crop→OCR→postprocess for a list of images.

    Returns a dict safe to embed into the evidence JSON bundle.
    """
    detector = ROIDetector(model_path=roi_model_path)
    cropper = ROICropper()
    patterns = {}
    allowlist: List[str] | None = None
    if pack is not None:
        try:
            patterns = dict(pack.ocr_patterns or {})
        except Exception:
            patterns = {}
        try:
            allowlist = list(pack.roi_allowlist or [])
        except Exception:
            allowlist = None

    # Merge optional shared config packs (roadmap references these; packs can override).
    cv_cfg = _load_cv_config()
    try:
        shared_patterns = (cv_cfg.get("ocr_patterns.json") or {}).get("shared") or {}
        if isinstance(shared_patterns, dict):
            for k, v in shared_patterns.items():
                if k not in patterns:
                    patterns[k] = v
    except Exception:
        pass
    try:
        pid = getattr(pack, "id", None) if pack is not None else None
        pack_patterns = (cv_cfg.get("ocr_patterns.json") or {}).get(pid or "") or {}
        if isinstance(pack_patterns, dict):
            for k, v in pack_patterns.items():
                if k not in patterns:
                    patterns[k] = v
    except Exception:
        pass
    try:
        if allowlist is None or not allowlist:
            classes = (cv_cfg.get("roi_classes.json") or {}).get("classes")
            if isinstance(classes, list):
                allowlist = [str(c) for c in classes if c]
    except Exception:
        pass
    ocr = OCRPipeline(provider=ocr_provider, patterns=patterns)

    per_image: List[Dict[str, Any]] = []
    merged_fields: Dict[str, Any] = {}
    max_images = _cap_int("CV_MAX_IMAGES", 6, lo=1, hi=50)
    max_bytes = _cap_int("CV_MAX_IMAGE_BYTES", 5_000_000, lo=10_000, hi=50_000_000)
    max_dim = _cap_int("CV_NORMALIZE_MAX_DIM", 1280, lo=256, hi=4096)

    # When using the synthetic "embedded" OCR provider (tests/dev), preserve PNG metadata
    # so `extract_embedded_text()` continues to work.
    effective_ocr_provider = (os.getenv("CV_OCR_PROVIDER") or ocr_provider or "").strip().lower()
    preserve_metadata = effective_ocr_provider == "embedded"

    for idx, (fname, b) in enumerate((images or [])[:max_images]):
        if b is None:
            b = b""
        if len(b) > max_bytes:
            per_image.append(
                {
                    "filename": fname,
                    "skipped": "too_large",
                    "size_bytes": len(b),
                    "rois": [],
                    "ocr": {"best_text": "", "best_confidence": 0.0, "runs": []},
                    "fields": {},
                }
            )
            continue

        if preserve_metadata:
            norm = normalize_image_bytes(b, max_dim=max_dim)
            img_bytes = b
            # Keep meta for visibility, but skip applying normalized bytes.
            try:
                norm = type(norm)(image_bytes=b, meta={**(norm.meta or {}), "skipped": "preserve_embedded_metadata"})
            except Exception:
                pass
        else:
            norm = normalize_image_bytes(b, max_dim=max_dim)
            img_bytes = norm.image_bytes
        rois = detector.detect(img_bytes, allowlist=allowlist)
        crops = cropper.crop_with_meta(img_bytes, rois)
        ocr_runs: List[Dict[str, Any]] = []
        best_text = ""
        best_fields: Dict[str, Any] = {}
        best_conf = 0.0
        for c in crops:
            r = ocr.run(c["image_bytes"])
            fields = r.get("fields") or {}
            ocr_runs.append(
                {
                    "roi": c.get("roi"),
                    "text": r.get("text") or "",
                    "confidence": float(r.get("confidence") or 0.0),
                    "provider": r.get("provider"),
                    "fields": fields,
                }
            )
            t = r.get("text") or ""
            conf = float(r.get("confidence") or 0.0)
            if (conf > best_conf) or (len(t) > len(best_text)):
                best_text = t
                best_conf = conf
                if isinstance(fields, dict):
                    best_fields = fields

        for k in ("order_id", "serial"):
            if k not in merged_fields and best_fields.get(k):
                merged_fields[k] = best_fields.get(k)

        per_image.append(
            {
                "filename": fname,
                "normalize": norm.meta,
                "rois": rois,
                "ocr": {"best_text": best_text, "best_confidence": best_conf, "runs": ocr_runs},
                "fields": best_fields,
            }
        )

    return {
        "images": per_image,
        "fields": merged_fields,
        "pack_id": getattr(pack, "id", None),
        "pack_version": getattr(pack, "version", None),
        "caps": {"max_images": max_images, "max_image_bytes": max_bytes, "normalize_max_dim": max_dim},
    }


def _ocr_variants_for_region(
    img_region: Any,
    gray_region: Any,
    prefix: str,
    *,
    clahe_obj: Any = None,
) -> List[Tuple[str, Any]]:
    """Build a list of (name, image) contrast variants for a single image region."""
    from PIL import Image, ImageOps, ImageEnhance  # type: ignore
    variants: List[Tuple[str, Any]] = [
        (f"{prefix}_base", img_region),
        (f"{prefix}_gray", gray_region),
        (f"{prefix}_inverted", ImageOps.invert(gray_region)),
    ]
    try:
        variants.append((f"{prefix}_high_contrast", ImageEnhance.Contrast(gray_region).enhance(2.4)))
    except Exception:
        pass
    if clahe_obj is not None:
        try:
            import numpy as np  # type: ignore
            import cv2  # type: ignore
            arr = np.array(gray_region)
            arr_clahe = clahe_obj.apply(arr)
            arr_adapt = cv2.adaptiveThreshold(
                arr_clahe, 255,
                cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                cv2.THRESH_BINARY, 25, 5,
            )
            variants.append((f"{prefix}_clahe", Image.fromarray(arr_clahe)))  # type: ignore[name-defined]
            variants.append((f"{prefix}_adaptive", Image.fromarray(arr_adapt)))  # type: ignore[name-defined]
        except Exception:
            pass
    return variants


def run_risk_triggered_multicontrast_ocr(
    image_bytes: bytes,
    *,
    ocr_provider: str | None = None,
    enabled: bool = True,
) -> Dict[str, Any]:
    """Deep OCR path for suspicious images only.

    Caller is expected to gate this behind Stage-1 risk signals.
    Scans these zones to detect adversarial low-contrast text anywhere in the image:

    Zone 0  — full image (base + grayscale + inverted + high-contrast + CLAHE)
    Zone 1  — bottom band  (lower 38% — existing)
    Zone 2  — right-side band  (right 38% — NEW: detects text near trackpad)
    Zone 3  — top band  (upper 20%)
    Zone 4  — quadrant grid  (TL, TR, BL, BR — 4 cells)
    Zone 5  — sliding-window  (3×2 grid with 20% overlap — full coverage)
    """
    if not enabled or not image_bytes:
        return {"best_text": "", "best_confidence": 0.0, "runs": [], "triggered": False}
    try:
        from PIL import Image, ImageOps, ImageEnhance  # type: ignore
        from io import BytesIO
    except Exception:
        return {"best_text": "", "best_confidence": 0.0, "runs": [], "triggered": True, "error": "pil_unavailable"}

    ocr = OCRPipeline(provider=ocr_provider)
    runs: List[Dict[str, Any]] = []
    best_text = ""
    best_conf = 0.0
    base_text = ""
    base_conf = 0.0

    try:
        img = Image.open(BytesIO(image_bytes)).convert("RGB")
        gray = ImageOps.grayscale(img)
        w, h = img.size

        # ── Prepare CLAHE once (requires cv2; degrades gracefully without it) ──
        clahe_obj = None
        try:
            import cv2  # type: ignore
            import numpy as np  # type: ignore
            clahe_obj = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        except Exception:
            pass

        all_variants: List[Tuple[str, Any]] = []

        # ── Zone 0: full image ──
        all_variants += _ocr_variants_for_region(img, gray, "full", clahe_obj=clahe_obj)

        # ── Zone 1: bottom band (lower 38%) ──
        try:
            band_top = int(max(0, h * 0.62))
            bb = img.crop((0, band_top, w, h))
            all_variants += _ocr_variants_for_region(
                bb, ImageOps.grayscale(bb), "bottom_band", clahe_obj=clahe_obj
            )
        except Exception:
            pass

        # ── Zone 2: right-side band (right 38%) ── NEW
        # Catches adversarial low-contrast text overlaid near trackpad / right margin.
        try:
            band_left = int(max(0, w * 0.62))
            rb = img.crop((band_left, 0, w, h))
            all_variants += _ocr_variants_for_region(
                rb, ImageOps.grayscale(rb), "right_band", clahe_obj=clahe_obj
            )
        except Exception:
            pass

        # ── Zone 3: top band (upper 20%) ──
        try:
            band_bot = int(min(h, h * 0.20))
            tb = img.crop((0, 0, w, band_bot))
            all_variants += _ocr_variants_for_region(
                tb, ImageOps.grayscale(tb), "top_band", clahe_obj=clahe_obj
            )
        except Exception:
            pass

        # ── Zone 4: quadrant grid (TL / TR / BL / BR) ──
        try:
            mw, mh = w // 2, h // 2
            for q_name, box in (
                ("quad_tl", (0, 0, mw, mh)),
                ("quad_tr", (mw, 0, w, mh)),
                ("quad_bl", (0, mh, mw, h)),
                ("quad_br", (mw, mh, w, h)),
            ):
                qr = img.crop(box)
                all_variants += _ocr_variants_for_region(
                    qr, ImageOps.grayscale(qr), q_name, clahe_obj=clahe_obj
                )
        except Exception:
            pass

        # ── Zone 5: sliding-window 3×2 grid with 20% overlap ──
        # 3 columns × 2 rows = 6 tiles, each overlapping 20% with neighbours.
        # Ensures no text is missed at tile borders.
        try:
            cols, rows = 3, 2
            step_x = w // cols
            step_y = h // rows
            overlap_x = int(step_x * 0.20)
            overlap_y = int(step_y * 0.20)
            for row in range(rows):
                for col in range(cols):
                    x0 = max(0, col * step_x - overlap_x)
                    y0 = max(0, row * step_y - overlap_y)
                    x1 = min(w, (col + 1) * step_x + overlap_x)
                    y1 = min(h, (row + 1) * step_y + overlap_y)
                    tile = img.crop((x0, y0, x1, y1))
                    tile_name = f"win_r{row}c{col}"
                    # Only grayscale + CLAHE for sliding-window tiles (perf budget)
                    tile_gray = ImageOps.grayscale(tile)
                    all_variants.append((tile_name, tile_gray))
                    if clahe_obj is not None:
                        try:
                            arr_t = np.array(tile_gray)
                            arr_t_clahe = clahe_obj.apply(arr_t)
                            all_variants.append((f"{tile_name}_clahe", Image.fromarray(arr_t_clahe)))
                        except Exception:
                            pass
        except Exception:
            pass

        # ── Run OCR on every variant ──
        for v_name, im in all_variants:
            try:
                buf = BytesIO()
                im.save(buf, format="PNG")
                out = ocr.run(buf.getvalue())
                text = str(out.get("text") or "")
                conf = float(out.get("confidence") or 0.0)
                runs.append({"pass": v_name, "text": text, "confidence": conf})
                if v_name == "full_base":
                    base_text = text
                    base_conf = conf
                if conf > best_conf or len(text) > len(best_text):
                    best_text, best_conf = text, conf
            except Exception:
                pass

    except Exception:
        return {"best_text": "", "best_confidence": 0.0, "runs": runs, "triggered": True, "error": "deep_ocr_failed"}

    invisible_text_suspected = bool(
        (len(base_text.strip()) < 6 and len(best_text.strip()) >= 16)
        or (base_conf < 0.2 and best_conf >= 0.5 and len(best_text.strip()) >= 10)
    )
    return {
        "best_text": best_text,
        "best_confidence": best_conf,
        "runs": runs,
        "triggered": True,
        "invisible_text_suspected": invisible_text_suspected,
    }
