from __future__ import annotations

from typing import Any, Dict, List

from src.app.services.cv_model_pack import get_model_pack
from src.app.services.cv_object_detector import CVObjectDetector
from src.app.services.cv_ocr import extract_text
from src.app.services.cv_quality import score_quality
from src.app.services.image_forensics import ImageForensicsService, ForensicsResult
from src.app.services.forensics_policy import evaluate as evaluate_forensics_policy
from src.app.observability.metrics import record_cv_fraud
from src.app.security.framework_correlation import correlate_security_analysis

import difflib
import math
import re


_URL_RE = re.compile(r"https?://[^\s<>()\"']+")


def _detect_document_like(ocr_boxes: List[Dict[str, Any]]) -> bool:
    if not ocr_boxes:
        return False
    # Heuristic: many text boxes in a compact layout suggests document/label.
    return len(ocr_boxes) >= 8


def _similarity(a: str, b: str) -> float:
    try:
        return float(difflib.SequenceMatcher(None, a or "", b or "").ratio())
    except Exception:
        return 0.0


def _shannon_entropy(s: str) -> float:
    s = str(s or "")
    if not s:
        return 0.0
    freq: dict[str, int] = {}
    for ch in s:
        freq[ch] = freq.get(ch, 0) + 1
    n = float(len(s))
    ent = 0.0
    for c in freq.values():
        p = float(c) / n
        ent -= p * math.log2(p)
    return float(ent)


def _extract_qr_payloads(image_bytes: bytes) -> Dict[str, Any]:
    # Best-effort QR/barcode extraction. If dependencies are missing, return empty.
    try:
        from PIL import Image  # type: ignore
        from pyzbar.pyzbar import decode  # type: ignore
        import io

        img = Image.open(io.BytesIO(image_bytes))
        decoded = decode(img)
        payloads: List[Dict[str, Any]] = []
        for d in decoded or []:
            try:
                val = (d.data.decode("utf-8", errors="ignore") if getattr(d, "data", None) else "") or ""
                if val.strip():
                    payloads.append({"type": str(getattr(d, "type", "unknown")), "value": val.strip()[:4096]})
            except Exception:
                continue
        return {"provider": "pyzbar", "items": payloads}
    except Exception as exc:
        return {"provider": "none", "items": [], "error": str(exc)}


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

    # Dual OCR robustness (optional). Helps detect OCR-adversarial typography and disagreement.
    dual_ocr = None
    try:
        enabled = str(ocr_cfg.get("dual_enabled") or "").strip().lower() in ("1", "true", "yes") or str(__import__("os").getenv("CV_DUAL_OCR_ENABLED", "0")).lower() in ("1", "true", "yes")
    except Exception:
        enabled = False
    try:
        dual_providers = ocr_cfg.get("dual_providers") if isinstance(ocr_cfg.get("dual_providers"), list) else []
    except Exception:
        dual_providers = []
    if enabled and len(dual_providers) >= 2:
        try:
            ocr_a = extract_text(image_bytes, provider=str(dual_providers[0]), fallback=None)
            ocr_b = extract_text(image_bytes, provider=str(dual_providers[1]), fallback=None)
            ta = str(ocr_a.get("text") or "")
            tb = str(ocr_b.get("text") or "")
            sim = _similarity(ta[:2000], tb[:2000])
            dual_ocr = {
                "providers": [ocr_a.get("provider"), ocr_b.get("provider")],
                "similarity": round(sim, 4),
                "a_conf": ocr_a.get("confidence"),
                "b_conf": ocr_b.get("confidence"),
            }
            if ta.strip() and tb.strip() and sim < 0.6:
                record_cv_fraud("robustness_ocr_dual_disagreement")
        except Exception:
            dual_ocr = {"error": "dual_ocr_failed"}

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

    # QR/barcode extraction gate: extract payloads and evaluate URL-like values.
    qr = _extract_qr_payloads(image_bytes)
    qr_urls: List[str] = []
    try:
        for item in (qr.get("items") or []):
            v = str((item or {}).get("value") or "")
            if _URL_RE.search(v):
                qr_urls.append(_URL_RE.search(v).group(0))  # type: ignore[union-attr]
    except Exception:
        qr_urls = []
    if qr_urls:
        evidence_tags.append("qr_url_present")
        record_cv_fraud("robustness_qr_url_present")

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

    # Framework correlation for decision trace drilldown (CV lane).
    # Keep conservative: only use derived signals/tags and policy verdict.
    try:
        sig = {
            "manipulation_detected": "manipulation_detected" in evidence_tags,
            "qr_url_present": "qr_url_present" in evidence_tags,
            "layout_text_divergence": False,  # reserved for PDF layout diff lane
            "ocr_adversarial_typography": bool(dual_ocr and isinstance(dual_ocr, dict) and float(dual_ocr.get("similarity") or 1.0) < 0.6),
        }
    except Exception:
        sig = {}
    try:
        # CV lane doesn't always have DREAD/CVSS; reuse threat_enrichment when ATLAS tags apply.
        # For now, map manipulation/QR into ATLAS evasion/obfuscation.
        tc = {
            "mitre_attack": ["AML.T0015"] if (sig.get("manipulation_detected") or sig.get("ocr_adversarial_typography")) else [],
            "dread": {"damage": 6.5, "reproducibility": 6.0, "exploitability": 5.8, "affected_users": 4.8, "discoverability": 6.2, "avg": 5.86},
            "cvss": {"score": 6.4, "severity": "medium", "vector": "AV:N/AC:L/PR:N/UI:R/S:U/C:M/I:M/A:L"},
            "kev": [],
        }
    except Exception:
        tc = {}
    try:
        sec = correlate_security_analysis(
            channel="cv",
            severity=str((verdict or {}).get("verdict") or ""),
            tags=evidence_tags,
            reasons=list((verdict or {}).get("reasons") or []),
            threat_correlation=tc,
            signals=sig,
            evidence={"robustness": {"dual_ocr": dual_ocr, "qr": qr}},
        )
    except Exception:
        sec = None

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
        "security_analysis": sec,
        "robustness": {
            "dual_ocr": dual_ocr,
            "qr": qr,
            "qr_url_count": len(qr_urls),
            "ocr_text_entropy": round(_shannon_entropy(ocr_text[:800]), 4),
        },
    }
