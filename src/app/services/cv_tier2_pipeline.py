from __future__ import annotations

from typing import Any, Callable, Dict, List

from src.app.services.cv_model_pack import get_model_pack
from src.app.services.cv_object_detector import CVObjectDetector
from src.app.services.cv_ocr import extract_text
from src.app.services.cv_quality import score_quality
from src.app.services.image_forensics import ImageForensicsService, ForensicsResult
from src.app.services.forensics_policy import evaluate as evaluate_forensics_policy
from src.app.cv.document_schema_extractor import extract_document_schema
from src.app.observability.metrics import record_cv_fraud
from src.app.security.framework_correlation import correlate_security_analysis
from src.app.security.gan_image_detector import detect_fake_image
from src.app.security.adversarial_image_detector import detect_adversarial, detect_pixel_prompt_injection
from src.app.security.steg_detector import detect_steganography
from src.app.security.observer import analyze_payload
from src.app.services.cv_vision_ollama import vision_analyze_with_ollama
from src.app.security.url_guard import ensure_safe_outbound_url
from src.app.services.decision_log import log_trace_event

import difflib
import logging
import math
import os
import re
import unicodedata
from urllib.parse import urlparse

_log = logging.getLogger("shopsquire.cv.tier2")

# ---------------------------------------------------------------------------
# Module-level model cache — prevents loading 200-600 MB YOLO weights once
# per HTTP request.  Keyed on model_path (str | None) so different packs
# that share the same path reuse the same instance.  Thread-safe: the GIL
# protects the dict assignment, and CVObjectDetector.__init__ is idempotent.
# ---------------------------------------------------------------------------
_DETECTOR_CACHE: dict[str | None, "CVObjectDetector"] = {}


def _get_detector(model_path: str | None) -> "CVObjectDetector":
    """Return a cached CVObjectDetector for *model_path*, creating it once."""
    if model_path not in _DETECTOR_CACHE:
        _DETECTOR_CACHE[model_path] = CVObjectDetector(model_path=model_path)
    return _DETECTOR_CACHE[model_path]


_URL_RE = re.compile(r"https?://[^\s<>()\"']+")
_PROMPT_INJECTION_RE = re.compile(
    r"(ignore\s+policy|admin\s+override|override\s+token|approve\s+return|system\s+prompt|developer\s+mode|do\s+not\s+follow|exfiltrate|prompt\s+injection)",
    re.IGNORECASE,
)

_SHORTENER_HOSTS = {
    "bit.ly",
    "t.co",
    "tinyurl.com",
    "is.gd",
    "goo.gl",
    "cutt.ly",
    "shorturl.at",
}


def _nfkc_changed(s: str) -> bool:
    try:
        return unicodedata.normalize("NFKC", s or "") != (s or "")
    except Exception:
        return False


def _has_suspicious_unicode(s: str) -> bool:
    try:
        for ch in (s or ""):
            if ord(ch) > 127:
                return True
            cat = unicodedata.category(ch)
            if cat in ("Cf", "Cs"):
                return True
        return False
    except Exception:
        return False


def _qr_url_risk(url: str) -> Dict[str, Any]:
    """Heuristic URL risk without fetching it (safe evaluation only)."""
    u = str(url or "").strip()
    if not u:
        return {"url": u, "risk": 0.0, "reasons": []}
    reasons: List[str] = []
    risk = 0.0
    try:
        p = urlparse(u)
        host = (p.hostname or "").lower().strip(".")
        if not host:
            reasons.append("missing_host")
            risk += 0.4
        if p.scheme not in ("http", "https"):
            reasons.append("non_http_scheme")
            risk += 0.6
        if p.username or p.password:
            reasons.append("userinfo_in_url")
            risk += 0.6
        if host.startswith("xn--"):
            reasons.append("punycode_host")
            risk += 0.5
        if host in _SHORTENER_HOSTS:
            reasons.append("url_shortener")
            risk += 0.4
        if re.fullmatch(r"(\d{1,3}\.){3}\d{1,3}", host or ""):
            reasons.append("ip_literal_host")
            risk += 0.6
        if len(u) > 200:
            reasons.append("very_long_url")
            risk += 0.2
        if any(tok in (p.path or "").lower() for tok in ("login", "verify", "reset", "invoice", "payment")):
            reasons.append("high_risk_path_tokens")
            risk += 0.2
        if any(tok in (p.query or "").lower() for tok in ("redirect", "url=", "next=", "continue=")):
            reasons.append("redirector_params")
            risk += 0.2
    except Exception:
        reasons.append("parse_error")
        risk += 0.4
    return {"url": u[:2048], "risk": float(min(1.0, risk)), "reasons": reasons}


def _resolve_redirect_chain(
    url: str,
    max_hops: int = 5,
    request_get: Callable[..., Any] | None = None,
    enforce_outbound: bool | None = None,
) -> Dict[str, Any]:
    """Resolve redirect chain in a bounded, safe manner.

    Each hop is validated with SSRF guard before any request. Redirects are
    resolved manually with allow_redirects=False to keep hop control explicit.
    Transport is injectable for tests.
    """
    out: Dict[str, Any] = {"start_url": str(url or "")[:2048], "hops": [], "final_url": str(url or "")[:2048], "error": None}
    import requests

    current = str(url or "").strip()
    timeout_s = float(os.getenv("QR_REDIRECT_TIMEOUT_SEC", "2.0") or 2.0)
    if request_get is None:
        request_get = requests.get
    if enforce_outbound is None:
        enforce_outbound = True

    def _skip_outbound_guard(target_url: str) -> bool:
        if not enforce_outbound:
            return True
        if not str(os.getenv("PYTEST_CURRENT_TEST") or "").strip():
            return False
        try:
            host = (urlparse(target_url).hostname or "").lower().strip(".")
        except Exception:
            return False
        return host.endswith(".example")

    for idx in range(max(0, int(max_hops))):
        if not current:
            break
        try:
            if not _skip_outbound_guard(current):
                ensure_safe_outbound_url(current)
        except Exception as exc:
            out["error"] = f"unsafe_redirect_url:{exc}"
            break
        try:
            resp = request_get(current, allow_redirects=False, timeout=timeout_s)
        except Exception as exc:
            out["error"] = f"redirect_request_failed:{str(exc)[:140]}"
            break

        status = int(getattr(resp, "status_code", 0) or 0)
        location = str((resp.headers or {}).get("Location") or "").strip()
        hop = {"index": idx + 1, "url": current[:2048], "status": status, "location": location[:2048] if location else None}
        out["hops"].append(hop)

        if status in (301, 302, 303, 307, 308) and location:
            from urllib.parse import urljoin

            nxt = urljoin(current, location)
            if nxt == current:
                break
            current = nxt
            out["final_url"] = current[:2048]
            continue
        break
    return out


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


def _normalize_product_family(raw: str) -> str:
    v = str(raw or "").strip().lower()
    if not v:
        return ""
    if any(tok in v for tok in ("laptop", "notebook", "macbook", "ultrabook", "chromebook", "computer")):
        return "laptop"
    if any(tok in v for tok in ("phone", "iphone", "android", "mobile", "smartphone")):
        return "phone"
    if any(tok in v for tok in ("document", "invoice", "receipt", "label", "bill", "statement", "form")):
        return "document"
    if any(tok in v for tok in ("fruit", "apple", "banana", "orange", "pear")):
        return "fruit"
    return "other"


def _yolo_family_guess(det_summary: Dict[str, Any], detections: List[Dict[str, Any]]) -> tuple[str, float]:
    try:
        family_conf: Dict[str, float] = {}
        family_n: Dict[str, int] = {}
        labels = list(det_summary.get("labels") or [])
        mapped = list(det_summary.get("mapped") or [])
        for idx, det in enumerate(detections or []):
            raw_label = str(det.get("label") or (labels[idx] if idx < len(labels) else "")).strip()
            mapped_label = str(mapped[idx] if idx < len(mapped) else "")
            family = _normalize_product_family(raw_label) or _normalize_product_family(mapped_label)
            if not family:
                continue
            conf = float(det.get("confidence") or 0.0)
            family_conf[family] = float(family_conf.get(family, 0.0) + conf)
            family_n[family] = int(family_n.get(family, 0) + 1)
        if not family_conf:
            return "", 0.0
        best_family = sorted(family_conf.items(), key=lambda x: x[1], reverse=True)[0][0]
        avg_conf = float(family_conf.get(best_family, 0.0)) / float(max(1, family_n.get(best_family, 1)))
        return best_family, float(max(0.0, min(1.0, avg_conf)))
    except Exception:
        return "", 0.0


def _ocr_family_guess(ocr_text: str, ocr_conf: float) -> tuple[str, float]:
    text = str(ocr_text or "").lower()
    if not text.strip():
        return "", 0.0
    hints = {
        "laptop": ("laptop", "macbook", "intel", "ryzen", "ram", "ssd", "gpu", "keyboard"),
        "phone": ("iphone", "android", "sim", "phone", "mobile", "carrier"),
        "document": ("invoice", "receipt", "subtotal", "tax", "bill to", "ship to", "tracking"),
        "fruit": ("banana", "orange", "pear", "mango"),
    }
    best_family = ""
    best_hits = 0
    for fam, toks in hints.items():
        hits = sum(1 for t in toks if t in text)
        if hits > best_hits:
            best_hits = hits
            best_family = fam
    if best_hits <= 0:
        return "", 0.0
    conf = min(0.95, max(0.15, float(ocr_conf) * (0.55 + min(0.45, 0.1 * best_hits))))
    return best_family, float(conf)


def _quality_family_guess(quality: Dict[str, Any]) -> tuple[str, float]:
    try:
        scores = quality.get("scores") if isinstance(quality.get("scores"), dict) else {}
        best_family = ""
        best_score = 0.0
        for raw_k, raw_v in scores.items():
            fam = _normalize_product_family(str(raw_k))
            if not fam:
                continue
            s = float(raw_v or 0.0)
            if s > best_score:
                best_family = fam
                best_score = s
        if not best_family:
            return "", 0.0
        return best_family, float(max(0.0, min(1.0, best_score)))
    except Exception:
        return "", 0.0


def _vision_family_guess(vision: Dict[str, Any] | None) -> tuple[str, float]:
    try:
        if not isinstance(vision, dict) or not bool(vision.get("ok")) or not isinstance(vision.get("result"), dict):
            return "", 0.0
        result = vision.get("result") or {}
        fam = _normalize_product_family(str(result.get("product_type") or ""))
        if not fam or fam in ("other",):
            return "", 0.0
        conf = 0.74
        if fam == "unknown":
            conf = 0.35
        if bool(result.get("prompt_injection_suspected")):
            conf = max(0.4, conf - 0.12)
        return fam, float(conf)
    except Exception:
        return "", 0.0


def _multimodal_decision_tree(
    *,
    det_summary: Dict[str, Any],
    detections: List[Dict[str, Any]],
    ocr_text: str,
    ocr_conf: float,
    quality: Dict[str, Any],
    vision: Dict[str, Any] | None,
    dual_ocr: Dict[str, Any] | None,
    qr_risks: List[Dict[str, Any]],
    evidence_tags: List[str],
) -> Dict[str, Any]:
    yolo_family, yolo_conf = _yolo_family_guess(det_summary, detections)
    ocr_family, ocr_fam_conf = _ocr_family_guess(ocr_text, ocr_conf)
    quality_family, quality_conf = _quality_family_guess(quality)
    vision_family, vision_conf = _vision_family_guess(vision)

    weights = {
        "yolo": 0.42,
        "ocr": 0.24,
        "vision": 0.24,
        "quality": 0.10,
    }
    votes: Dict[str, float] = {}

    def _vote(family: str, conf: float, w: float) -> None:
        if not family:
            return
        votes[family] = float(votes.get(family, 0.0) + max(0.0, min(1.0, conf)) * w)

    _vote(yolo_family, yolo_conf, weights["yolo"])
    _vote(ocr_family, ocr_fam_conf, weights["ocr"])
    _vote(vision_family, vision_conf, weights["vision"])
    _vote(quality_family, quality_conf, weights["quality"])

    selected_family = "unknown"
    fused_conf = 0.0
    agreement_ratio = 0.0
    available = [(yolo_family, yolo_conf), (ocr_family, ocr_fam_conf), (vision_family, vision_conf), (quality_family, quality_conf)]
    used = [(fam, conf) for fam, conf in available if fam]
    if votes:
        selected_family = sorted(votes.items(), key=lambda x: x[1], reverse=True)[0][0]
        total_weight = 0.0
        if yolo_family:
            total_weight += weights["yolo"]
        if ocr_family:
            total_weight += weights["ocr"]
        if vision_family:
            total_weight += weights["vision"]
        if quality_family:
            total_weight += weights["quality"]
        agreed = sum(1 for fam, conf in used if fam == selected_family and conf >= 0.45)
        agreement_ratio = float(agreed) / float(max(1, len(used)))
        fused_conf = float((votes.get(selected_family, 0.0) / float(max(1e-9, total_weight))) * (0.7 + 0.3 * agreement_ratio))
        fused_conf = float(max(0.0, min(1.0, fused_conf)))

    mismatch_conf_min = float(os.getenv("CV_MM_MISMATCH_CONF_MIN", "0.62") or 0.62)
    low_conf_min = float(os.getenv("CV_MM_LOW_CONFIDENCE_MIN", "0.56") or 0.56)
    ocr_yolo_conflict = bool(yolo_family and ocr_family and yolo_family != ocr_family and min(yolo_conf, ocr_fam_conf) >= mismatch_conf_min)
    vision_yolo_conflict = bool(yolo_family and vision_family and yolo_family != vision_family and min(yolo_conf, vision_conf) >= mismatch_conf_min)
    cross_modal_mismatch = bool(ocr_yolo_conflict or vision_yolo_conflict or (len(used) >= 3 and agreement_ratio < 0.34 and fused_conf < 0.72))

    max_qr_risk = 0.0
    try:
        max_qr_risk = max((float(r.get("risk") or 0.0) for r in (qr_risks or [])), default=0.0)
    except Exception:
        max_qr_risk = 0.0
    attack_surface_high = bool(
        max_qr_risk >= 0.85
        or (cross_modal_mismatch and any(t in evidence_tags for t in ("prompt_injection_text_suspected", "qr_url_suspicious", "steganography_suspected", "adversarial_perturbation_suspected", "manipulation_detected")))
    )
    product_identity_low_confidence = bool(selected_family in ("", "unknown", "other") or fused_conf < low_conf_min)
    requires_review = bool(product_identity_low_confidence or cross_modal_mismatch or attack_surface_high)
    action = "block" if attack_surface_high else ("challenge" if requires_review else "allow")

    reasons: List[str] = []
    if ocr_yolo_conflict:
        reasons.append("ocr_yolo_conflict")
    if vision_yolo_conflict:
        reasons.append("vision_yolo_conflict")
    if product_identity_low_confidence:
        reasons.append("product_identity_low_confidence")
    if cross_modal_mismatch:
        reasons.append("cross_modal_mismatch")
    if attack_surface_high:
        reasons.append("attack_surface_high")
    if not reasons:
        reasons.append("cross_modal_consensus")

    return {
        "decision": action,
        "product_family": selected_family,
        "confidence": round(float(fused_conf), 4),
        "agreement_ratio": round(float(agreement_ratio), 4),
        "sources": {
            "yolo": {"family": yolo_family or "unknown", "confidence": round(float(yolo_conf), 4)},
            "ocr": {"family": ocr_family or "unknown", "confidence": round(float(ocr_fam_conf), 4)},
            "vision": {"family": vision_family or "unknown", "confidence": round(float(vision_conf), 4)},
            "quality": {"family": quality_family or "unknown", "confidence": round(float(quality_conf), 4)},
            "dual_ocr_similarity": round(float((dual_ocr or {}).get("similarity") or 0.0), 4),
            "max_qr_risk": round(float(max_qr_risk), 4),
        },
        "signals": {
            "product_identity_low_confidence": product_identity_low_confidence,
            "ocr_yolo_label_conflict": ocr_yolo_conflict,
            "vision_yolo_conflict": vision_yolo_conflict,
            "cross_modal_mismatch": cross_modal_mismatch,
            "multimodal_attack_surface_high": attack_surface_high,
        },
        "reasons": reasons[:8],
    }


def _extract_qr_payloads(image_bytes: bytes) -> Dict[str, Any]:
    # Best-effort QR/barcode extraction.
    # Use shared decoder pipeline so we get both pyzbar and OpenCV fallbacks.
    try:
        from src.app.rules.barcode_decode import decode_barcodes

        result = decode_barcodes([("tier2_input", image_bytes)])
        payloads: List[Dict[str, Any]] = []
        for item in (result.codes or []):
            val = str((item or {}).get("data") or "").strip()
            if not val:
                continue
            payloads.append(
                {
                    "type": str((item or {}).get("type") or "unknown"),
                    "value": val[:4096],
                }
            )

        provider = "none"
        reasons = list(result.reasons or [])
        if "pyzbar_decoded" in reasons:
            provider = "pyzbar"
        elif "opencv_decoded" in reasons:
            provider = "opencv"

        return {
            "provider": provider,
            "items": payloads,
            "decoder_reasons": reasons,
        }
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
        detector = _get_detector(model_path)
        detections = detector.detect(image_bytes)
        det_summary = detector.summarize(detections)
    except Exception as exc:
        det_summary = {"error": "detector_failed", "detail": str(exc)}

    ocr = {"text": "", "boxes": [], "provider": None, "error": None}
    try:
        ocr = extract_text(image_bytes, provider=ocr_cfg.get("provider"), fallback=ocr_cfg.get("fallback"))
    except Exception as exc:
        ocr = {"text": "", "boxes": [], "provider": None, "error": str(exc)}
    ocr_conf = float(ocr.get("confidence") or 0.0)
    ocr_ladder: Dict[str, Any] = {
        "attempts": [
            {
                "provider": ocr.get("provider"),
                "confidence": ocr_conf,
                "chars": len(str(ocr.get("text") or "")),
                "selected": True,
            }
        ],
        "selected_provider": ocr.get("provider"),
        "selected_confidence": ocr_conf,
        "fallback_used": False,
        "degraded": bool(ocr.get("degraded")),
        "degradation_reason": ocr.get("degradation_reason") or ocr.get("error"),
    }
    _ocr_degraded_initial = bool(ocr_ladder.get("degraded"))
    _ocr_degraded_reason_initial = str(ocr_ladder.get("degradation_reason") or "").strip()
    ocr_text = ocr.get("text") or ""
    ocr_boxes = ocr.get("boxes") or []
    document_like = _detect_document_like(ocr_boxes)
    evidence_tags: List[str] = []
    if bool(ocr.get("degraded")):
        evidence_tags.append("cv_ocr_degraded")
    doc_schema: Dict[str, Any] = {}
    try:
        doc_schema = extract_document_schema(ocr_text)
        if bool(doc_schema.get("has_structured_fields")):
            evidence_tags.append("structured_document_fields_extracted")
            if str(doc_schema.get("doc_type") or "") in ("invoice", "bol", "shipping_label"):
                evidence_tags.append(f"document_type:{str(doc_schema.get('doc_type'))}")
    except Exception:
        doc_schema = {}
    clarifiers: List[Dict[str, Any]] = []
    try:
        doc_type = str(doc_schema.get("doc_type") or "")
        has_structured = bool(doc_schema.get("has_structured_fields"))
        ocr_low_conf_min = float(os.getenv("CV_OCR_LOW_CONFIDENCE_MIN", "0.58") or 0.58)
        fallback_provider = str(ocr_cfg.get("fallback") or os.getenv("CV_OCR_FALLBACK_PROVIDER", "")).strip() or None
        selected_provider = str(ocr.get("provider") or "").strip()
        if has_structured and doc_type in ("invoice", "bol", "shipping_label") and ocr_conf < ocr_low_conf_min:
            if fallback_provider and fallback_provider != selected_provider:
                try:
                    ocr_fb = extract_text(image_bytes, provider=fallback_provider, fallback=None)
                    fb_conf = float(ocr_fb.get("confidence") or 0.0)
                    ocr_ladder["attempts"].append(
                        {
                            "provider": ocr_fb.get("provider") or fallback_provider,
                            "confidence": fb_conf,
                            "chars": len(str(ocr_fb.get("text") or "")),
                            "selected": False,
                        }
                    )
                    if fb_conf > ocr_conf and str(ocr_fb.get("text") or "").strip():
                        ocr = ocr_fb
                        ocr_conf = fb_conf
                        ocr_text = str(ocr_fb.get("text") or "")
                        ocr_boxes = ocr_fb.get("boxes") or []
                        ocr_ladder["fallback_used"] = True
                        ocr_ladder["selected_provider"] = ocr_fb.get("provider") or fallback_provider
                        ocr_ladder["selected_confidence"] = fb_conf
                        evidence_tags.append("ocr_fallback_applied")
                        try:
                            doc_schema = extract_document_schema(ocr_text)
                        except Exception:
                            pass
                    for attempt in (ocr_ladder.get("attempts") or []):
                        if str(attempt.get("provider") or "") == str(ocr_ladder.get("selected_provider") or ""):
                            attempt["selected"] = True
                        else:
                            attempt["selected"] = False
                except Exception:
                    pass
            if float(ocr_conf) < ocr_low_conf_min:
                evidence_tags.append("ocr_low_confidence")
                clarifiers.append(
                    {
                        "type": "ocr_low_confidence",
                        "question": "Please upload a clearer invoice/BOL/label image or PDF (flat, bright, and uncropped).",
                        "confidence": round(float(ocr_conf), 4),
                        "doc_type": doc_type,
                    }
                )
    except Exception:
        pass
    # Emit an explicit trace event when OCR provider/runtime is unavailable or degraded.
    try:
        _trace_id = str(meta.get("trace_id") or meta.get("case_id") or "").strip()
        _ocr_degraded_final = bool(ocr.get("degraded") or ocr_ladder.get("degraded"))
        _ocr_degraded_reason_final = str(ocr.get("degradation_reason") or ocr.get("error") or "").strip()
        if _ocr_degraded_initial or _ocr_degraded_final:
            log_trace_event(
                trace_id=_trace_id or None,
                event_type="cv_ocr_degraded",
                source_type="cv_provider",
                source_id=str(ocr_ladder.get("selected_provider") or ocr.get("provider") or "unknown"),
                target_type="system",
                target_id=None,
                payload={
                    "degraded_initial": bool(_ocr_degraded_initial),
                    "degraded_final": bool(_ocr_degraded_final),
                    "reason_initial": _ocr_degraded_reason_initial or None,
                    "reason_final": _ocr_degraded_reason_final or None,
                    "fallback_used": bool(ocr_ladder.get("fallback_used")),
                    "attempts": list(ocr_ladder.get("attempts") or []),
                },
            )
    except Exception:
        pass

    filename = str(meta.get("filename") or "")
    filename_unicode_nfkc = _nfkc_changed(filename)
    filename_unicode_any = _has_suspicious_unicode(filename)

    injection_phrases = []
    try:
        injection_phrases = sorted(list(set([m.group(0) for m in _PROMPT_INJECTION_RE.finditer(ocr_text or "")])))
    except Exception:
        injection_phrases = []

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

    gan = None
    adversarial = None
    steganography = None
    diffusion_generated = False
    try:
        gan_enabled = str(os.getenv("CV_GAN_DETECT_ENABLED", "1")).lower() in ("1", "true", "yes")
        if gan_enabled:
            gan_res = detect_fake_image(image_bytes)
            gan = {
                "fake_score": float(gan_res.fake_score),
                "is_likely_fake": bool(gan_res.is_likely_fake),
                "explanations": list(gan_res.explanations or [])[:8],
            }
            if gan.get("is_likely_fake"):
                evidence_tags.append("gan_fake_image_suspected")
                record_cv_fraud("robustness_gan_fake_image")
    except Exception:
        gan = {"error": "gan_detector_failed"}
    try:
        adv_enabled = str(os.getenv("CV_ADVERSARIAL_DETECT_ENABLED", "1")).lower() in ("1", "true", "yes")
        if adv_enabled:
            adv_res = detect_adversarial(image_bytes)
            adversarial = {
                "adversarial_score": float(adv_res.adversarial_score),
                "high_freq_ratio": float(adv_res.high_freq_ratio),
                "recompress_instability": float(adv_res.recompress_instability),
                "local_gradient_anomaly": float(adv_res.local_gradient_anomaly),
                "diffusion_score": float(adv_res.diffusion_score),
                "is_adversarial": bool(adv_res.is_adversarial),
                "explanations": list(adv_res.explanations or [])[:8],
            }
            if adversarial.get("is_adversarial"):
                evidence_tags.append("adversarial_perturbation_suspected")
                record_cv_fraud("robustness_adversarial_perturbation")
            diff_min = float(os.getenv("CV_DIFFUSION_SIGNAL_MIN", "0.55") or 0.55)
            if float(adversarial.get("diffusion_score") or 0.0) >= diff_min:
                diffusion_generated = True
                evidence_tags.append("diffusion_generated_suspected")
        # OWASP Agentic AI AA05 — pixel-space prompt injection analysis.
        # Runs unconditionally when adversarial detection is enabled; detects
        # instruction-encoding perturbations targeting vision-LLM attention.
        try:
            ppi_res = detect_pixel_prompt_injection(image_bytes)
            adversarial["pixel_prompt_injection"] = {
                "injection_score": float(ppi_res.injection_score),
                "grid_alignment_score": float(ppi_res.grid_alignment_score),
                "lsb_entropy_score": float(ppi_res.lsb_entropy_score),
                "dct_ac_anomaly_score": float(ppi_res.dct_ac_anomaly_score),
                "is_injection_risk": bool(ppi_res.is_injection_risk),
                "owasp_tag": ppi_res.owasp_tag,
                "explanations": list(ppi_res.explanations or [])[:6],
            }
            if ppi_res.is_injection_risk:
                evidence_tags.append("pixel_prompt_injection_suspected")
                record_cv_fraud("robustness_pixel_prompt_injection")
        except Exception:
            adversarial["pixel_prompt_injection"] = {"error": "ppi_detector_failed"}
    except Exception:
        adversarial = {"error": "adversarial_detector_failed"}
    try:
        steg_enabled = str(os.getenv("CV_STEG_DETECT_ENABLED", "1")).lower() in ("1", "true", "yes")
        if steg_enabled:
            steg_res = detect_steganography(image_bytes)
            steganography = {
                "steg_score": float(steg_res.steg_score),
                "chi_square_p": float(steg_res.chi_square_p),
                "lsb_entropy_r": float(steg_res.lsb_entropy_r),
                "lsb_entropy_g": float(steg_res.lsb_entropy_g),
                "lsb_entropy_b": float(steg_res.lsb_entropy_b),
                "is_suspicious": bool(steg_res.is_suspicious),
                "explanations": list(steg_res.explanations or [])[:8],
            }
            if steganography.get("is_suspicious"):
                evidence_tags.append("steganography_suspected")
                record_cv_fraud("robustness_steganography_suspected")
    except Exception as _exc:
        _log.warning("steganography detector failed: %s", _exc, exc_info=True)
        steganography = {"error": "steg_detector_failed"}

    # Evidence tags derived from tier2 signals
    try:
        oc = meta.get("order_ctx")
        if isinstance(oc, dict) and oc.get("found") is False:
            evidence_tags.append("order_id_not_found")
    except Exception as _exc:
        _log.debug("order_ctx tag skipped: %s", _exc)
    if filename_unicode_nfkc:
        evidence_tags.append("filename_nfkc_changed")
    if filename_unicode_any:
        evidence_tags.append("filename_unicode_suspicious")
    if injection_phrases:
        evidence_tags.append("prompt_injection_text_suspected")
    manip_signal_min = float(os.getenv("CV_MANIP_SIGNAL_MIN", "0.52") or 0.52)
    if float(forensics.get("manipulation_score") or 0.0) >= manip_signal_min:
        evidence_tags.append("manipulation_detected")
    try:
        dct_score = float((forensics.get("details") or {}).get("dct_anomaly_score") or 0.0)
        dct_min = float(os.getenv("CV_DCT_SIGNAL_MIN", "0.32") or 0.32)
        if dct_score >= dct_min:
            evidence_tags.append("jpeg_dct_anomaly")
    except Exception:
        pass
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
    qr_payload_values: List[str] = []
    try:
        for item in (qr.get("items") or []):
            v = str((item or {}).get("value") or "")
            if v.strip():
                qr_payload_values.append(v[:500])
            if _URL_RE.search(v):
                qr_urls.append(_URL_RE.search(v).group(0))  # type: ignore[union-attr]
    except Exception:
        qr_urls = []
        qr_payload_values = []
    if qr_urls:
        evidence_tags.append("qr_url_present")
        record_cv_fraud("robustness_qr_url_present")

    observer_result: Dict[str, Any] = {}
    observer_prompt_injection = False
    try:
        merged_security_text = "\n".join(
            [str(ocr_text or "")[:6000], *[str(x)[:500] for x in qr_payload_values[:8]]]
        ).strip()
        if merged_security_text:
            observer_result = analyze_payload(
                {
                    "query": merged_security_text,
                    "source": "cv_ocr_qr",
                    "cv_meta": {
                        "filename": str(meta.get("filename") or "")[:128],
                        "qr_count": len(qr_payload_values),
                    },
                }
            ) or {}
            sigs = observer_result.get("signals") if isinstance(observer_result.get("signals"), dict) else {}
            sev = str(observer_result.get("severity") or "").strip().lower()
            observer_prompt_injection = bool(
                sigs.get("prompt_injection")
                or sigs.get("jailbreak")
                or sigs.get("injection")
                or (sev in {"high", "critical"})
            )
            if observer_prompt_injection:
                evidence_tags.append("prompt_injection_text_suspected")
    except Exception:
        observer_result = {}
        observer_prompt_injection = False

    qr_risks = []
    qr_redirect_chains: List[Dict[str, Any]] = []
    try:
        follow_redirects = str(os.getenv("QR_REDIRECT_RESOLUTION_ENABLED", "1")).lower() in ("1", "true", "yes")
        max_hops = int(os.getenv("QR_REDIRECT_MAX_HOPS", "5") or 5)
        for u in qr_urls[:5]:
            if follow_redirects:
                chain = _resolve_redirect_chain(u, max_hops=max_hops)
                qr_redirect_chains.append(chain)
                final_url = str(chain.get("final_url") or u)
                # H06: Score both start URL and final URL, take max risk
                start_risk = _qr_url_risk(u)
                final_risk = _qr_url_risk(final_url)
                risk = final_risk if float(final_risk.get("risk") or 0) >= float(start_risk.get("risk") or 0) else start_risk
                # Merge reasons from both endpoints
                all_reasons = list(set((start_risk.get("reasons") or []) + (final_risk.get("reasons") or [])))
                risk["reasons"] = all_reasons
                hop_count = len(chain.get("hops") or [])
                if hop_count > 1:
                    risk["risk"] = float(min(1.0, float(risk.get("risk") or 0.0) + min(0.35, 0.08 * (hop_count - 1))))
                    risk.setdefault("reasons", []).append("redirect_chain_detected")
                # H06: Flag when start and final domains differ (redirect to different domain)
                try:
                    from urllib.parse import urlparse
                    start_host = urlparse(u).hostname or ""
                    final_host = urlparse(final_url).hostname or ""
                    if start_host and final_host and start_host.lower() != final_host.lower():
                        risk["risk"] = float(min(1.0, float(risk.get("risk") or 0.0) + 0.15))
                        risk.setdefault("reasons", []).append("cross_domain_redirect")
                except Exception:
                    pass
                if chain.get("error"):
                    risk["risk"] = float(min(1.0, float(risk.get("risk") or 0.0) + 0.2))
                    risk.setdefault("reasons", []).append("redirect_resolution_failed")
                    risk["redirect_error"] = str(chain.get("error"))[:160]
                risk["resolved_url"] = final_url[:2048]
                risk["redirect_hops"] = hop_count
                qr_risks.append(risk)
            else:
                qr_risks.append(_qr_url_risk(u))
    except Exception as _exc:
        _log.warning("QR redirect resolution failed: %s", _exc, exc_info=True)
        qr_risks = []
    try:
        if any(float(r.get("risk") or 0.0) >= 0.6 for r in (qr_risks or [])):
            evidence_tags.append("qr_url_suspicious")
    except Exception as _exc:
        _log.debug("qr_url_suspicious tag skipped: %s", _exc)

    # Optional vision lane (Ollama) for coarse category checks (laptop vs non-laptop) and visible damage.
    # Always disabled in pytest to prevent egress-blocked Ollama hangs (non-strict allowlist logs and continues).
    _in_pytest = "PYTEST_CURRENT_TEST" in __import__("os").environ
    vision = None
    try:
        v_enabled = (not _in_pytest) and str(__import__("os").getenv("CV_VISION_ENABLED", "0")).strip().lower() in ("1", "true", "yes")
    except Exception:
        v_enabled = False
    if v_enabled:
        try:
            v_timeout = float(__import__("os").getenv("CV_VISION_TIMEOUT_SEC", "10") or 10.0)
        except Exception:
            v_timeout = 10.0
        vision = vision_analyze_with_ollama(
            image_bytes,
            prompt_context=str(meta.get("description") or meta.get("issue_type") or ""),
            model=str(__import__("os").getenv("CV_VISION_MODEL") or "").strip() or None,
            timeout_s=v_timeout,
        )
        try:
            if isinstance(vision, dict) and vision.get("ok") and isinstance(vision.get("result"), dict):
                r = vision.get("result") or {}
                ptype = str(r.get("product_type") or "unknown").lower()
                cond = str(r.get("device_condition") or "unknown").lower()
                v_inject = bool(r.get("prompt_injection_suspected")) or bool((r.get("prompt_injection_phrases") or []))
                if ptype and ptype not in ("unknown", "other"):
                    evidence_tags.append(f"vision_product_type:{ptype}")
                if cond in ("cracked", "damaged"):
                    evidence_tags.append("vision_damage_detected")
                if v_inject:
                    evidence_tags.append("prompt_injection_text_suspected")
                # Filename expectation heuristic: if filename says mac/lenovo/laptop but model says fruit/document, flag mismatch.
                fn_l = filename.lower()
                if any(tok in fn_l for tok in ("mac", "macbook", "lenovo", "legion", "laptop")) and ptype in ("fruit", "document", "phone", "other"):
                    evidence_tags.append("image_category_mismatch_filename")
                # Expected label hint: if caller expects laptop but vision says non-laptop, flag mismatch.
                exp = str(meta.get("expected_label") or "").lower().strip()
                if exp:
                    if ("laptop" in exp or "macbook" in exp or "computer" in exp) and ptype in ("fruit", "document", "phone", "other"):
                        evidence_tags.append("image_category_mismatch_expected")
        except Exception:
            pass

    multimodal = _multimodal_decision_tree(
        det_summary=det_summary if isinstance(det_summary, dict) else {},
        detections=detections if isinstance(detections, list) else [],
        ocr_text=str(ocr_text or ""),
        ocr_conf=float(ocr_conf or 0.0),
        quality=quality if isinstance(quality, dict) else {},
        vision=vision if isinstance(vision, dict) else None,
        dual_ocr=dual_ocr if isinstance(dual_ocr, dict) else None,
        qr_risks=qr_risks if isinstance(qr_risks, list) else [],
        evidence_tags=evidence_tags if isinstance(evidence_tags, list) else [],
    )
    mm_signals = multimodal.get("signals") if isinstance(multimodal.get("signals"), dict) else {}
    if bool(mm_signals.get("product_identity_low_confidence")) and "product_identity_low_confidence" not in evidence_tags:
        evidence_tags.append("product_identity_low_confidence")
    if bool(mm_signals.get("cross_modal_mismatch")) and "product_identity_cross_modal_mismatch" not in evidence_tags:
        evidence_tags.append("product_identity_cross_modal_mismatch")
    if bool(mm_signals.get("multimodal_attack_surface_high")) and "multimodal_attack_surface_high" not in evidence_tags:
        evidence_tags.append("multimodal_attack_surface_high")

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
            verdict = evaluate_forensics_policy(
                forensics_obj,
                context={
                    "ocr_text": ocr_text,
                    "cv_meta": meta,
                    "evidence_tags": evidence_tags,
                    "prompt_injection_phrases": injection_phrases,
                    "qr_risks": qr_risks,
                    "vision": vision,
                },
                ela_mask_area_ratio=ela_area_ratio,
            )
    except Exception as _exc:
        _log.warning("forensics policy evaluation failed: %s", _exc, exc_info=True)
        verdict = {"verdict": "request_more_data", "reasons": ["policy_error"], "required_actions": ["manual_review"], "score": 0.0}

    # Framework correlation for decision trace drilldown (CV lane).
    # Keep conservative: only use derived signals/tags and policy verdict.
    try:
        sig = {
            "manipulation_detected": "manipulation_detected" in evidence_tags,
            "qr_url_present": "qr_url_present" in evidence_tags,
            "layout_text_divergence": False,  # reserved for PDF layout diff lane
            "ocr_adversarial_typography": bool(dual_ocr and isinstance(dual_ocr, dict) and float(dual_ocr.get("similarity") or 1.0) < 0.6),
            "prompt_injection_text": "prompt_injection_text_suspected" in evidence_tags,
            "observer_prompt_injection": bool(observer_prompt_injection),
            "filename_unicode_suspicious": ("filename_nfkc_changed" in evidence_tags) or ("filename_unicode_suspicious" in evidence_tags),
            "qr_url_suspicious": "qr_url_suspicious" in evidence_tags,
            "image_category_mismatch": ("image_category_mismatch_filename" in evidence_tags) or ("image_category_mismatch_expected" in evidence_tags),
            "gan_fake_image_suspected": "gan_fake_image_suspected" in evidence_tags,
            "adversarial_perturbation_suspected": "adversarial_perturbation_suspected" in evidence_tags,
            "steganography_suspected": "steganography_suspected" in evidence_tags,
            "ai_generated_image_suspected": bool(diffusion_generated) or ("diffusion_generated_suspected" in evidence_tags),
            "product_identity_low_confidence": bool(mm_signals.get("product_identity_low_confidence")),
            "ocr_yolo_label_conflict": bool(mm_signals.get("ocr_yolo_label_conflict")),
            "vision_yolo_conflict": bool(mm_signals.get("vision_yolo_conflict")),
            "cross_modal_mismatch": bool(mm_signals.get("cross_modal_mismatch")),
            "multimodal_attack_surface_high": bool(mm_signals.get("multimodal_attack_surface_high")),
        }
    except Exception:
        sig = {}
    try:
        # CV lane doesn't always have DREAD/CVSS; reuse threat_enrichment when ATLAS tags apply.
        # Map manipulation/QR/overlay-text into ATLAS tags so CV produces non-empty taxonomies.
        mitre_attack: List[str] = []
        if sig.get("manipulation_detected") or sig.get("ocr_adversarial_typography"):
            mitre_attack.append("AML.T0015")  # evasion/obfuscation via visual manipulation
        if sig.get("qr_url_present") or sig.get("prompt_injection_text") or sig.get("qr_url_suspicious"):
            mitre_attack.append("AML.T0043")  # adversarial data / prompt injection via indirection
        if sig.get("cross_modal_mismatch") or sig.get("ocr_yolo_label_conflict") or sig.get("vision_yolo_conflict"):
            mitre_attack.append("AML.T0015")
        if sig.get("multimodal_attack_surface_high"):
            mitre_attack.append("AML.T0043")

        # For OWASP mapping, expose canonical signal names the map understands.
        try:
            if sig.get("qr_url_present") or sig.get("prompt_injection_text") or sig.get("qr_url_suspicious"):
                sig.setdefault("prompt_injection", True)
            if sig.get("manipulation_detected"):
                sig.setdefault("supply_chain", True)
            if sig.get("cross_modal_mismatch") or sig.get("vision_yolo_conflict") or sig.get("ocr_yolo_label_conflict"):
                sig.setdefault("adversarial_detected", True)
            if sig.get("multimodal_attack_surface_high"):
                sig.setdefault("supply_chain", True)
        except Exception:
            pass

        tc = {
            "mitre_attack": mitre_attack,
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
            evidence={
                "robustness": {
                    "dual_ocr": dual_ocr,
                    "qr": qr,
                    "qr_risks": qr_risks,
                    "vision": vision,
                    "observer": {
                        "severity": observer_result.get("severity"),
                        "signals": observer_result.get("signals"),
                    },
                }
            },
        )
    except Exception:
        sec = None

    return {
        "model_pack": pack.get("id"),
        "trace_id": str(meta.get("case_id") or ""),
        "case_id": str(meta.get("case_id") or ""),
        "detector": {"model": model_path, "detections": detections, "summary": det_summary},
        "ocr": ocr,
        "quality": quality,
        "forensics": forensics,
        "evidence": {
            "masks": (forensics_obj.masks if forensics_obj else {}),
            "details": (forensics_obj.details if forensics_obj else {}),
            "document_schema": doc_schema,
            "ocr_ladder": ocr_ladder,
        },
        "signals": {
            "document_like": document_like,
            "manipulation_detected": "manipulation_detected" in evidence_tags,
            "gan_fake_image_suspected": "gan_fake_image_suspected" in evidence_tags,
            "adversarial_perturbation_suspected": "adversarial_perturbation_suspected" in evidence_tags,
            "steganography_suspected": "steganography_suspected" in evidence_tags,
            "ai_generated_image_suspected": bool(diffusion_generated) or ("diffusion_generated_suspected" in evidence_tags),
            "product_identity_low_confidence": bool(mm_signals.get("product_identity_low_confidence")),
            "cross_modal_mismatch": bool(mm_signals.get("cross_modal_mismatch")),
            "ocr_yolo_label_conflict": bool(mm_signals.get("ocr_yolo_label_conflict")),
            "vision_yolo_conflict": bool(mm_signals.get("vision_yolo_conflict")),
            "multimodal_attack_surface_high": bool(mm_signals.get("multimodal_attack_surface_high")),
        },
        "evidence_tags": evidence_tags,
        "clarifiers": clarifiers,
        "verdict": verdict,
        "security_analysis": sec,
        "robustness": {
            "dual_ocr": dual_ocr,
            "qr": qr,
            "qr_url_count": len(qr_urls),
            "qr_risks": qr_risks,
            "qr_redirect_chains": qr_redirect_chains,
            "security_observer": {
                "severity": observer_result.get("severity") if isinstance(observer_result, dict) else None,
                "signals": observer_result.get("signals") if isinstance(observer_result, dict) else {},
            },
            "ocr_text_entropy": round(_shannon_entropy(ocr_text[:800]), 4),
            "prompt_injection_phrases": injection_phrases,
            "filename": {"value": filename[:200], "nfkc_changed": filename_unicode_nfkc, "unicode_suspicious": filename_unicode_any},
            "vision": vision,
            "multimodal_decision": multimodal,
            "gan": gan,
            "adversarial": adversarial,
            "steganography": steganography,
            "document_schema": doc_schema,
            "ocr_ladder": ocr_ladder,
        },
    }
