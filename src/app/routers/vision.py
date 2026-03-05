from fastapi import APIRouter, UploadFile, File, Depends, HTTPException
from typing import Any, Dict, List, Optional
import json
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
async def triage(image: UploadFile = File(...), role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER]))) -> Dict:
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
    provider_name = "none"
    try:
        provider = ManagedCVProvider()
        provider_name = provider.provider
        labels, extracted_text = await provider.get_labels_and_text(content)
    except Exception:
        labels, extracted_text = [], ""

    if not labels and name:
        labels = [name]

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
    qr_product_data: Dict[str, Any] = {}
    try:
        from src.app.rules.barcode_decode import decode_barcodes
        qr = decode_barcodes([(str(name or "image.jpg"), content)])
        qr_codes = qr.codes if hasattr(qr, "codes") else (qr if isinstance(qr, list) else [])
        if qr_codes:
            security_signals["qr_code_detected"] = True
            security_clean = False
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
    try:
        from src.app.security.steg_detector import detect_steganography
        steg = detect_steganography(content)
        if hasattr(steg, "is_suspicious") and steg.is_suspicious:
            security_signals["steg_suspicious"] = True
            security_clean = False
        if hasattr(steg, "composite_score"):
            security_signals["steg_score"] = round(float(steg.composite_score), 3)
    except Exception:
        pass

    resp["security"] = {
        "clean": security_clean,
        "signals": security_signals,
        "reupload_needed": not security_clean,
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
