from __future__ import annotations

from typing import Any, Dict, List

from src.app.services.cv_model_pack import get_model_pack
from src.app.services.cv_object_detector import CVObjectDetector
from src.app.services.cv_ocr import extract_text
from src.app.services.cv_quality import score_quality
from src.app.services.image_forensics import ImageForensicsService, ForensicsResult
from src.app.services.forensics_policy import evaluate as evaluate_forensics_policy


def _detect_document_like(ocr_boxes: List[Dict[str, Any]]) -> bool:
    if not ocr_boxes:
        return False
    # Heuristic: many text boxes in a compact layout suggests document/label.
    return len(ocr_boxes) >= 8


def run_tier2(image_bytes: bytes, meta: Dict[str, Any] | None = None, pack_id: str | None = None) -> Dict[str, Any]:
    meta = meta or {}
    pack = get_model_pack(pack_id)
    detector_cfg = (pack.get("detector") or {}) if isinstance(pack.get("detector"), dict) else {}
    ocr_cfg = (pack.get("ocr") or {}) if isinstance(pack.get("ocr"), dict) else {}
    quality_cfg = (pack.get("quality") or {}) if isinstance(pack.get("quality"), dict) else {}

    model_path = detector_cfg.get("model") or None
    detections = []
    det_summary = {"labels": [], "mapped": [], "unique": [], "counts": {}}
    try:
        detector = CVObjectDetector(model_path=model_path)
        detections = detector.detect(image_bytes)
        det_summary = detector.summarize(detections)
    except Exception as exc:
        det_summary = {"error": "detector_failed", "detail": str(exc)}

    ocr = {"text": "", "boxes": [], "provider": None, "error": None}
    try:
        ocr = extract_text(image_bytes, provider=ocr_cfg.get("provider"), fallback=ocr_cfg.get("fallback"))
    except Exception as exc:
        ocr = {"text": "", "boxes": [], "provider": None, "error": str(exc)}
    ocr_text = ocr.get("text") or ""
    ocr_boxes = ocr.get("boxes") or []
    document_like = _detect_document_like(ocr_boxes)

    forensics: Dict[str, Any] = {}
    forensics_obj: ForensicsResult | None = None
    try:
        if pack.get("forensics"):
            svc = ImageForensicsService()
            forensics_obj = svc.analyze(image_bytes, context={"case_meta": meta})
            # Dict form for backwards-compatibility / JSON response
            forensics = {
                "manipulation_score": forensics_obj.manipulation_score,
                "splice_score": forensics_obj.splice_score,
                "copy_move_score": forensics_obj.copy_move_score,
                "double_compress_score": forensics_obj.double_compress_score,
                "blur_score": forensics_obj.blur_score,
                "metadata": forensics_obj.metadata_flags,
                "masks": forensics_obj.masks,
                "hashes": forensics_obj.hashes,
                "explanations": forensics_obj.explanations,
                "details": forensics_obj.details,
            }
    except Exception as exc:
        forensics = {"error": "forensics_failed", "detail": str(exc)}
    quality_labels = quality_cfg.get("labels") if isinstance(quality_cfg.get("labels"), list) else []
    if quality_labels:
        try:
            quality = score_quality(image_bytes, quality_labels)
        except Exception as exc:
            quality = {"scores": {}, "provider": "clip", "error": str(exc)}
    else:
        quality = {"scores": {}, "provider": "clip"}

    # Evidence tags derived from tier2 signals
    evidence_tags: List[str] = []
    if float(forensics.get("manipulation_score") or 0.0) >= 0.6:
        evidence_tags.append("manipulation_detected")
    if document_like:
        if "invoice" in ocr_text.lower() or "receipt" in ocr_text.lower():
            evidence_tags.append("invoice_mismatch")
        if "serial" in ocr_text.lower() or "sn" in ocr_text.lower():
            evidence_tags.append("serial_mismatch")
    # If quality model flags blurry photo with high probability, note as evidence tag
    try:
        blur_score = float((quality.get("scores") or {}).get("blurry photo") or 0.0)
        if blur_score >= 0.6:
            evidence_tags.append("image_blurry")
    except Exception:
        pass

    # Compute ELA mask area ratio for verdict policy
    ela_area_ratio = 0.0
    try:
        from PIL import Image as _PILImage
        img = _PILImage.open(__import__("io").BytesIO(image_bytes)).convert("RGB")
        w, h = img.size
        bboxes = (forensics_obj.masks.get("ela") if forensics_obj else []) or []
        total = 0
        for b in bboxes:
            total += max(0, int(b.get("max_x", 0)) - int(b.get("min_x", 0))) * max(0, int(b.get("max_y", 0)) - int(b.get("min_y", 0)))
        ela_area_ratio = float(total) / float(max(1, w * h))
    except Exception:
        pass

    # Verdict policy
    verdict = None
    try:
        if forensics_obj:
            verdict = evaluate_forensics_policy(forensics_obj, context={"ocr_text": ocr_text, "cv_meta": meta}, ela_mask_area_ratio=ela_area_ratio)
    except Exception:
        verdict = {"verdict": "request_more_data", "reasons": ["policy_error"], "required_actions": ["manual_review"], "score": 0.0}

    return {
        "model_pack": pack.get("id"),
        "detector": {"model": model_path, "detections": detections, "summary": det_summary},
        "ocr": ocr,
        "quality": quality,
        "forensics": forensics,
        "evidence": {
            "masks": (forensics_obj.masks if forensics_obj else {}),
            "details": (forensics_obj.details if forensics_obj else {}),
        },
        "signals": {
            "document_like": document_like,
            "manipulation_detected": "manipulation_detected" in evidence_tags,
        },
        "evidence_tags": evidence_tags,
        "verdict": verdict,
    }
