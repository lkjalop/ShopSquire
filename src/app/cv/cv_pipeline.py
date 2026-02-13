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
