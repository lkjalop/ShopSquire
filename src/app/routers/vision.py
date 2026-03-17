from fastapi import APIRouter, UploadFile, File, Depends, HTTPException, Query
from typing import Any, Dict, List, Optional
import json
import os
import uuid
import hashlib
import inspect

from src.app.models.event_log import ensure_event_log_table
from src.app.models.db import db_session
from src.app.security.auth import require_role, ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER
from src.app.services.cv_triage_basic import BasicCVTriage
from src.app.services.cv_provider import ManagedCVProvider
from src.app.services.image_intent_router import classify_image_intent
from src.app.services.intake_gate import strict_image_ingest_gate
from src.app.services.image_intake import sanitize_image
from src.app.routers.support_complaints import _normalize_ocr_and_detect, _probe_redirect_chain
from src.app.security.passive_payload_analysis import classify_passive_payload

router = APIRouter(prefix="/api/v1/vision", tags=["vision"])

# Product photo heuristic: labels that suggest a clean, undamaged product shot
_PRODUCT_LABEL_KW = {
    "laptop", "phone", "tablet", "monitor", "keyboard", "headphone",
    "camera", "printer", "router", "speaker", "watch", "console",
    "computer", "desktop", "mouse", "charger", "cable", "adapter",
}

_DAMAGE_LABEL_KW = {
    "crack", "broken", "dent", "scratch", "shatter", "damage",
    "defect", "torn", "crushed", "scuff", "stain",
}

_BRAND_HINT_KW = {
    "apple": ("apple", "macbook", "imac", "mac mini", "mac pro"),
    "msi": ("msi", "raider", "stealth", "creator", "thin a15", "modern 15"),
    "lenovo": ("lenovo", "thinkpad", "ideapad", "legion", "yoga"),
    "asus": ("asus", "vivobook", "zenbook", "rog", "tuf", "proart"),
    "dell": ("dell", "xps", "inspiron", "latitude", "precision", "alienware"),
    "hp": ("hp", "hewlett", "envy", "spectre", "pavilion", "omen", "victus", "zbook"),
    "microsoft": ("microsoft", "surface"),
    "acer": ("acer", "aspire", "nitro", "predator", "swift"),
}


def _compute_damage_score(analysis: Dict) -> float:
    """Derive a 0.0-1.0 damage score from CV triage analysis."""
    if not isinstance(analysis, dict):
        return 0.0
    confidence = float(analysis.get("confidence") or 0.0)
    damage_type = str(analysis.get("damage_type") or "").lower()
    severity = str(analysis.get("severity") or "").lower()
    if damage_type == "unknown" or analysis.get("insufficient_data"):
        return max(0.05, confidence * 0.2)
    severity_map = {"critical": 0.95, "major": 0.75, "minor": 0.45, "undetermined": 0.25}
    base = severity_map.get(severity, 0.3)
    return round(min(1.0, base * max(0.4, confidence)), 3)


def _is_product_photo(labels: List[str], damage_score: float) -> bool:
    """Heuristic: image is a clean product photo (not damage evidence)."""
    if damage_score > 0.4:
        return False
    label_text = " ".join(labels).lower()
    has_product = any(kw in label_text for kw in _PRODUCT_LABEL_KW)
    has_damage = any(kw in label_text for kw in _DAMAGE_LABEL_KW)
    return has_product and not has_damage


def _compute_image_hash(content: bytes) -> str:
    """SHA-256 of raw image bytes for dedup."""
    return hashlib.sha256(content).hexdigest()[:32]


def _labels_are_weak(labels: List[str]) -> bool:
    vals = [str(x).strip().lower() for x in (labels or []) if str(x).strip()]
    if not vals:
        return True
    return all(len(v) <= 8 or any(tok in v for tok in ("text", "overlay", "image", "photo")) for v in vals)


def _brand_hint_from_text(*parts: str) -> Optional[str]:
    combined = " ".join(str(p or "") for p in parts).lower()
    if not combined.strip():
        return None
    # Common weak MSI overlay artifact naming: "ms-texti", "ms texti".
    # Treat this as MSI only on the weak-label rescue path, not as a global alias.
    if any(tok in combined for tok in ("ms-texti", "ms texti")):
        return "msi"
    for brand, keywords in _BRAND_HINT_KW.items():
        if any(kw in combined for kw in keywords):
            return brand
    return None


def _derive_query_from_analysis(analysis: Dict) -> str:
    if not isinstance(analysis, dict):
        return "product"
    damage_type = str(analysis.get("damage_type") or "").lower()
    component = str(analysis.get("component") or "").lower()
    if damage_type and damage_type != "unknown":
        return f"{damage_type} {component}".strip()
    if component:
        return component
    return "device"


@router.post("/triage")
async def triage(
    image: UploadFile = File(...),
    fast: bool = Query(False),
    role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict:
    """Run lightweight CV triage from uploaded image and persist event metadata."""
    if image is None:
        raise HTTPException(status_code=400, detail="image_required")

    try:
        mime = image.content_type
        name = image.filename
    except Exception:
        mime = None
        name = None

    content = await image.read()
    if not content:
        raise HTTPException(status_code=400, detail="empty_image")
    gate = strict_image_ingest_gate(
        filename=str(name or "image.jpg"),
        content_type=mime,
        blob=content,
        size_bytes=len(content),
    )
    if bool(gate.get("blocked")):
        raise HTTPException(
            status_code=400,
            detail={
                "error": "ingest_gate_blocked",
                "message": "Upload blocked by strict ingest gate (type/size/archive/AV policy).",
                "ingest_gate": gate,
            },
        )
    try:
        sanitized = sanitize_image(content)
        if isinstance(sanitized, dict) and str(sanitized.get("status") or "") == "sanitized":
            content = sanitized.get("bytes") or content
    except Exception:
        pass

    labels = []
    extracted_text = ""
    product_identity = None
    provider_name = "fast_local" if fast else "none"
    if not fast:
        try:
            provider = ManagedCVProvider()
            provider_name = provider.provider
            labels, extracted_text, product_identity = await provider.get_labels_and_text(
                content, mode="visual_search",
            )
        except Exception:
            labels, extracted_text, product_identity = [], "", None

    # P3: Always append sanitized filename as a weak hint (not just when labels empty)
    if name:
        fname_hint = os.path.splitext(str(name).lower())[0].replace("-", " ").replace("_", " ")
        if fname_hint and fname_hint not in " ".join(labels).lower():
            labels = (labels or []) + [fname_hint]

    triager = BasicCVTriage()
    triage_result = triager.analyze(labels, extracted_text or "")
    if inspect.isawaitable(triage_result):
        analysis = await triage_result
    else:
        analysis = triage_result

    resp = {
        "query": _derive_query_from_analysis(analysis),
        "label": analysis.get("damage_type") or "unknown",
        "mime": mime,
        "filename": name,
        "provider": provider_name,
        "labels": labels[:20],
        "extracted_text": (extracted_text or "")[:500],
        "analysis": analysis,
        "damage_score": _compute_damage_score(analysis),
        "is_product_photo": _is_product_photo(labels, _compute_damage_score(analysis)),
        "image_hash": _compute_image_hash(content),
        "ingest_gate": gate,
    }

    # P4: Always surface product identity — decoupled from security flags.
    # Even security-flagged images carry brand/model info useful for recommendations.
    if product_identity:
        resp["product_identity"] = product_identity

    # Run image intent router for smart routing guidance
    try:
        intent_result = classify_image_intent(
            image_labels=labels[:12],
            image_ocr_text=(extracted_text or "")[:500],
            damage_score=resp["damage_score"],
            is_product_photo=resp["is_product_photo"],
        )
        resp["intent_routing"] = intent_result
    except Exception:
        resp["intent_routing"] = {"intent": "disambiguate", "confidence": 0.0, "reason": "router_error"}

    # Security scan: QR/barcode + adversarial detection (best-effort)
    security_clean = True
    security_signals: Dict[str, Any] = {}

    # P5: Cross-validate filename brand vs vision model brand (spoofing detection)
    try:
        from src.app.services.filename_brand_validator import validate_filename_vs_labels
        brand_validation = validate_filename_vs_labels(
            filename=str(name or ""),
            vision_labels=labels,
            product_identity=product_identity,
        )
        if brand_validation.get("mismatch"):
            security_signals["filename_brand_mismatch"] = True
            resp["brand_validation"] = brand_validation
    except Exception:
        pass

    qr_product_data: Dict[str, Any] = {}
    qr_redirect_probe: Dict[str, Any] = {"enabled": False, "checked": False, "chain": []}
    try:
        from src.app.rules.barcode_decode import decode_barcodes
        qr = decode_barcodes([(str(name or "image.jpg"), content)])
        qr_codes = qr.codes if hasattr(qr, "codes") else (qr if isinstance(qr, list) else [])
        if qr_codes:
            security_signals["qr_code_detected"] = True
            security_clean = False
            # Surface decoded QR payloads (first 5, truncated to 300 chars each)
            security_signals["qr_payloads"] = [
                {
                    "data": str(c.get("data") or "")[:300],
                    "type": str(c.get("type") or "QR_CODE"),
                    "payload_type": str(c.get("payload_type") or "other"),
                }
                for c in qr_codes[:5]
                if str(c.get("data") or "").strip()
            ]
            security_signals["qr_payload_types"] = list({
                str(c.get("payload_type") or "").strip()
                for c in qr_codes
                if str(c.get("payload_type") or "").strip()
            })
            # Check for prompt injection in QR data
            try:
                from src.app.routers.support_complaints import _detect_ocr_prompt_injection
                for c in qr_codes:
                    if _detect_ocr_prompt_injection(str(c.get("data") or "")):
                        security_signals["qr_prompt_injection"] = True
                        break
            except Exception:
                pass
            # Check for external URLs
            try:
                from urllib.parse import urlparse
                for c in qr_codes:
                    data = str(c.get("data") or "").strip()
                    if data.lower().startswith(("http://", "https://")):
                        host = (urlparse(data).hostname or "").lower()
                        if host and host not in ("127.0.0.1", "localhost"):
                            security_signals["qr_external_url"] = True
                            security_signals["qr_external_url_detected"] = True
                            if not fast:
                                try:
                                    qr_redirect_probe = await _probe_redirect_chain(data, timeout_s=1.25, max_hops=3)
                                except Exception:
                                    qr_redirect_probe = {"enabled": True, "checked": False, "chain": [], "error": "probe_exception"}
                            else:
                                qr_redirect_probe = {"enabled": False, "checked": False, "chain": [], "deferred": True}
                            break
            except Exception:
                pass
            # ── Productive QR data extraction ──
            # Extract useful product information from QR data (model URLs, serial numbers)
            try:
                from urllib.parse import urlparse as _qr_urlparse
                import re as _qr_re
                _MANUFACTURER_HOSTS = {
                    "apple.com", "www.apple.com", "store.apple.com",
                    "lenovo.com", "www.lenovo.com", "psref.lenovo.com",
                    "dell.com", "www.dell.com",
                    "hp.com", "www.hp.com", "support.hp.com",
                    "asus.com", "www.asus.com",
                    "acer.com", "www.acer.com",
                    "samsung.com", "www.samsung.com",
                    "microsoft.com", "www.microsoft.com",
                }
                for c in qr_codes:
                    data = str(c.get("data") or "").strip()
                    if not data:
                        continue
                    # URL-based product data
                    if data.lower().startswith(("http://", "https://")):
                        parsed = _qr_urlparse(data)
                        host = (parsed.hostname or "").lower()
                        if any(host.endswith(mfr) for mfr in _MANUFACTURER_HOSTS):
                            qr_product_data["manufacturer_url"] = data[:500]
                            # Extract brand from host
                            for mfr in ("apple", "lenovo", "dell", "hp", "asus", "acer", "samsung", "microsoft"):
                                if mfr in host:
                                    qr_product_data["brand_hint"] = mfr.capitalize()
                                    break
                            # Extract model from URL path segments
                            path_parts = [p for p in (parsed.path or "").split("/") if p]
                            if path_parts:
                                qr_product_data["url_path_hint"] = "/".join(path_parts[:3])
                    # Serial number / model number patterns (non-URL QR data)
                    else:
                        # Common serial/model patterns: alphanumeric 6-20 chars
                        sn_match = _qr_re.search(r'\b[A-Z0-9]{6,20}\b', data.upper())
                        if sn_match:
                            qr_product_data["serial_or_model_hint"] = sn_match.group()
                        # Check for structured data (JSON, key=value)
                        if "model" in data.lower() or "product" in data.lower():
                            qr_product_data["structured_data_hint"] = data[:200]
            except Exception:
                pass
    except Exception:
        pass

    if not fast:
        try:
            from src.app.security.adversarial_image_detector import detect_adversarial
            adv = detect_adversarial(content)
            if hasattr(adv, "is_adversarial") and adv.is_adversarial:
                security_signals["adversarial_detected"] = True
                security_clean = False
            if hasattr(adv, "diffusion_score") and adv.diffusion_score > 0.7:
                security_signals["ai_generated_suspected"] = True
        except Exception:
            pass

    # ── Fix 3: steganography detection ──
    if not fast:
        try:
            from src.app.security.steg_detector import detect_steganography
            steg = detect_steganography(content)
            steg_score = float(getattr(steg, "steg_score", 0.0) or 0.0)
            steg_elevated_min = float(os.getenv("CV_STEG_ELEVATED_MIN", "0.385") or 0.385)
            if hasattr(steg, "is_suspicious") and steg.is_suspicious:
                security_signals["steg_suspicious"] = True
                security_clean = False
            if steg_score:
                security_signals["steg_score"] = round(steg_score, 3)
            if steg_score >= steg_elevated_min:
                security_signals["steg_score_elevated"] = True
                security_clean = False
            if getattr(steg, "explanations", None):
                security_signals["steg_explanations"] = list(getattr(steg, "explanations", []) or [])[:8]
            if getattr(steg, "details", None):
                security_signals["steg_details"] = dict(getattr(steg, "details", {}) or {})
        except Exception:
            pass

    # OCR normalization + detector pass (PayID/PCI/crypto/ransom/encoded/unicode).
    try:
        ocr_det = _normalize_ocr_and_detect(extracted_text)
        stage_a_text = str(extracted_text or "").strip()
        deep_trigger = bool(
            (
                not stage_a_text
                and any(
                    bool(security_signals.get(sig))
                    for sig in (
                        "qr_code_detected",
                        "qr_external_url",
                        "qr_external_url_detected",
                        "filename_brand_mismatch",
                    )
                )
            )
            or (len(stage_a_text) < 12 and bool(security_signals.get("qr_code_detected")))
        )
        if deep_trigger and not fast:
            # Risk-triggered deep OCR for low-evidence or overlay-heavy images.
            from src.app.cv.cv_pipeline import run_risk_triggered_multicontrast_ocr
            deep = run_risk_triggered_multicontrast_ocr(content, ocr_provider=None, enabled=True)
            deep_text = str(deep.get("best_text") or "").strip()
            deep_conf = float(deep.get("best_confidence") or 0.0)
            deep_min_conf = float(os.getenv("CV_STAGE_B_OCR_CONFIDENCE_MIN", "0.45") or 0.45)
            if deep_text:
                extracted_text = deep_text[:500]
                ocr_det = _normalize_ocr_and_detect(extracted_text)
            if bool(deep.get("invisible_text_suspected")):
                security_signals["invisible_text_suspected"] = True
                security_clean = False
            # Stage-B still uncertain: keep visual flow available, but mark untrusted/degraded.
            if (not deep_text) or deep_conf < deep_min_conf:
                security_signals["ocr_low_confidence_uncertain"] = True
                security_clean = False

        if bool(ocr_det.get("payment_social_engineering")):
            security_signals["payment_social_engineering"] = True
            security_clean = False
        if bool(ocr_det.get("pci_card_exposed")):
            security_signals["pci_card_exposed"] = True
            security_clean = False
        if bool(ocr_det.get("crypto_payment_uri")):
            security_signals["crypto_payment_uri"] = True
            security_clean = False
        if bool(ocr_det.get("ransomware_indicator")):
            security_signals["ransomware_indicator"] = True
            security_clean = False
        if bool(ocr_det.get("encoded_payload_detected")):
            security_signals["encoded_payload_detected"] = True
            security_clean = False
        if bool(ocr_det.get("homoglyph_injection")):
            security_signals["homoglyph_injection"] = True
            security_clean = False
    except Exception:
        pass

    # Product identity rescue for weak/flagged product-like images.
    if not fast and not product_identity:
        try:
            weak_labels = _labels_are_weak(labels)
            flagged = bool(security_signals)
            product_like = _is_product_photo(labels, resp["damage_score"]) or any(
                kw in " ".join(str(x).lower() for x in (labels or []))
                for kw in _PRODUCT_LABEL_KW
            )
            if weak_labels or flagged or product_like:
                from src.app.services.product_identity_agent import (
                    identify_product_from_image,
                    identify_product_from_text,
                )

                hint_text = " ".join(labels or [])
                filename_hint = os.path.splitext(str(name or ""))[0].replace("-", " ").replace("_", " ")
                text_rescue = identify_product_from_text(
                    labels=labels or [],
                    ocr_text="",
                    user_query=filename_hint,
                    trace_id=None,
                )
                if bool(text_rescue.get("identified")) and str(text_rescue.get("brand") or "").strip():
                    product_identity = {
                        "brand": str(text_rescue.get("brand") or "").strip(),
                        "model": str(text_rescue.get("model") or "").strip() or None,
                        "category": str(text_rescue.get("product_type") or "laptop").strip().lower(),
                        "confidence": float(text_rescue.get("confidence") or 0.0),
                        "source": "visual_brand_hint",
                    }

                if not product_identity and not weak_labels:
                    direct_hint_brand = _brand_hint_from_text(hint_text, filename_hint)
                    if direct_hint_brand:
                        product_identity = {
                            "brand": direct_hint_brand.upper() if direct_hint_brand == "msi" else direct_hint_brand.capitalize(),
                            "model": None,
                            "category": "laptop",
                            "confidence": 0.31,
                            "source": "filename_or_label_hint",
                        }

                if not product_identity:
                    stage_b = identify_product_from_image(
                        content,
                        user_query=filename_hint or None,
                        trace_id=None,
                        timeout_s=float(os.getenv("CV_IDENTITY_STAGE_B_TIMEOUT_S", "6.0") or 6.0),
                    )
                    if isinstance(stage_b, dict):
                        brand = str(stage_b.get("brand") or "").strip()
                        if bool(stage_b.get("identified")) and brand:
                            product_identity = {
                                "brand": brand,
                                "model": str(stage_b.get("model") or "").strip() or None,
                                "category": str(stage_b.get("product_type") or "laptop").strip().lower(),
                                "confidence": float(stage_b.get("confidence") or 0.0),
                                "source": "vision_stage_b",
                            }
        except Exception:
            pass

    if product_identity:
        resp["product_identity"] = product_identity

    payload_analysis = classify_passive_payload(
        filename=str(name or ""),
        extracted_text=(extracted_text or "")[:500],
        signals=security_signals,
    )

    resp["security"] = {
        "clean": security_clean,
        "signals": security_signals,
        "reupload_needed": not security_clean,
        # Surface the OCR/extracted text here so the UI Security Matrix can show it
        "extracted_text": (extracted_text or "")[:500],
        "qr_redirect_probe": qr_redirect_probe,
        "analysis_stage": "fast" if fast else "full",
        "deferred_deep_analysis": bool(fast),
        "payload_analysis": payload_analysis,
        "decoded_artifact_available": payload_analysis.get("decoded_artifact_available"),
        "payload_type": payload_analysis.get("payload_type"),
        "attack_hypothesis": payload_analysis.get("attack_hypothesis"),
        "mitre_attack": payload_analysis.get("mitre_attack") or [],
        "decode_path": payload_analysis.get("decode_path"),
        "suggested_next_step": payload_analysis.get("suggested_next_step"),
    }
    # Attach productive QR data (manufacturer URLs, model hints) for downstream identity extraction
    if qr_product_data:
        resp["qr_product_data"] = qr_product_data
    if not security_clean:
        resp["security_message"] = (
            "For your security, we detected potentially unsafe content in this image. "
            "Please upload a new, unedited photo without QR codes or overlays."
        )

    try:
        ensure_event_log_table()
        ev_id = str(uuid.uuid4())
        payload = json.dumps(resp, ensure_ascii=False)

        def _persist_event():
            with db_session() as db:
                db.execute(
                    "INSERT INTO event_log (id, type, payload, status) VALUES (:id, :type, :payload, 'pending')",
                    {"id": ev_id, "type": "vision.triage", "payload": payload},
                )
                try:
                    db.commit()
                except Exception:
                    pass

        import asyncio
        await asyncio.to_thread(_persist_event)
        resp["event_id"] = ev_id
    except Exception:
        pass

    return resp
