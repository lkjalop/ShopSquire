from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import os
import uuid
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile

from src.app.deps import get_redis
from src.app.rules.tenant_config_store import TenantConfigStore
from src.app.security.auth import ROLE_DEVELOPER, ROLE_MERCHANT, ROLE_OWNER, require_role
from src.app.security.image_behavior_abuse import evaluate_behavioral_upload_abuse
from src.app.security.observer import analyze_payload, emit_security_event
from src.app.services.cv_provider import ManagedCVProvider
from src.app.services.cv_triage_basic import BasicCVTriage
from src.app.services.geoip import enrich_ip
from src.app.services.image_intent_router import classify_image_intent
from src.app.services.intake_gate import strict_image_ingest_gate


router = APIRouter(prefix="/api/v1/vision", tags=["vision"])

_PRODUCT_LABEL_KW = {
    "laptop",
    "phone",
    "tablet",
    "monitor",
    "keyboard",
    "headphone",
    "camera",
    "printer",
    "router",
    "speaker",
    "watch",
    "console",
    "computer",
    "desktop",
    "mouse",
    "charger",
    "cable",
    "adapter",
}

_DAMAGE_LABEL_KW = {
    "crack",
    "broken",
    "dent",
    "scratch",
    "shatter",
    "damage",
    "defect",
    "torn",
    "crushed",
    "scuff",
    "stain",
}

_VERDICT_ORDER = {"allow": 0, "challenge": 1, "escalate": 2, "block": 3}
_tenant_cfg_store = TenantConfigStore(cache_ttl=5)


def _raise_verdict(curr: str, nxt: str) -> str:
    a = str(curr or "allow")
    b = str(nxt or "allow")
    if _VERDICT_ORDER.get(b, 0) > _VERDICT_ORDER.get(a, 0):
        return b
    return a


def _compute_damage_score(analysis: Dict[str, Any]) -> float:
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
    if damage_score > 0.4:
        return False
    text = " ".join(labels).lower()
    has_product = any(kw in text for kw in _PRODUCT_LABEL_KW)
    has_damage = any(kw in text for kw in _DAMAGE_LABEL_KW)
    return bool(has_product and not has_damage)


def _qr_decode_signals(filename: str, blob: bytes) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "qr_code_detected": False,
        "qr_prompt_injection": False,
        "qr_external_url": False,
        "codes": [],
    }
    try:
        from src.app.rules.barcode_decode import decode_barcodes

        qr = decode_barcodes([(filename, blob)])
        codes = qr.codes if hasattr(qr, "codes") else (qr if isinstance(qr, list) else [])
        out["codes"] = codes or []
        if codes:
            out["qr_code_detected"] = True
            try:
                from src.app.routers.support_complaints import _detect_ocr_prompt_injection
                from urllib.parse import urlparse

                for c in codes:
                    data = str(c.get("data") or "")
                    if _detect_ocr_prompt_injection(data):
                        out["qr_prompt_injection"] = True
                    if data.lower().startswith(("http://", "https://")):
                        host = (urlparse(data).hostname or "").lower()
                        if host and host not in ("127.0.0.1", "localhost"):
                            out["qr_external_url"] = True
            except Exception:
                pass
    except Exception:
        pass
    return out


def _adversarial_and_steg(blob: bytes) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "adversarial_detected": False,
        "adversarial_score": 0.0,
        "diffusion_score": 0.0,
        "steg_suspicious": False,
        "steg_score": 0.0,
    }
    try:
        from src.app.security.adversarial_image_detector import detect_adversarial

        adv = detect_adversarial(blob)
        out["adversarial_detected"] = bool(getattr(adv, "is_adversarial", False))
        out["adversarial_score"] = float(getattr(adv, "adversarial_score", 0.0) or 0.0)
        out["diffusion_score"] = float(getattr(adv, "diffusion_score", 0.0) or 0.0)
    except Exception:
        pass
    try:
        from src.app.security.steg_detector import detect_steganography

        steg = detect_steganography(blob)
        out["steg_suspicious"] = bool(getattr(steg, "is_suspicious", False))
        out["steg_score"] = float(getattr(steg, "steg_score", 0.0) or 0.0)
    except Exception:
        pass
    return out


async def _extract_image_features(blob: bytes, filename: str) -> Dict[str, Any]:
    labels: List[str] = []
    extracted_text = ""
    provider_name = "none"
    try:
        provider = ManagedCVProvider()
        provider_name = str(getattr(provider, "provider", "unknown") or "unknown")
        labels, extracted_text, *_ = await provider.get_labels_and_text(blob)
    except Exception:
        labels, extracted_text = [], ""
    # P3: Always append sanitized filename as a weak hint
    if filename:
        fname_hint = os.path.splitext(str(filename).lower())[0].replace("-", " ").replace("_", " ")
        if fname_hint and fname_hint not in " ".join(labels).lower():
            labels = (labels or []) + [fname_hint]

    triager = BasicCVTriage()
    triage_result = triager.analyze(labels, extracted_text or "")
    analysis = await triage_result if inspect.isawaitable(triage_result) else triage_result
    if not isinstance(analysis, dict):
        analysis = {}

    damage_score = _compute_damage_score(analysis)
    image_hash = hashlib.sha256(blob).hexdigest()[:32]
    return {
        "provider": provider_name,
        "labels": labels[:20],
        "ocr_text": str(extracted_text or "")[:1200],
        "analysis": analysis,
        "damage_score": damage_score,
        "is_product_photo": _is_product_photo(labels, damage_score),
        "image_hash": image_hash,
    }


def _security_message(
    *,
    verdict: str,
    actions: Dict[str, Any],
) -> str | None:
    if bool(actions.get("reupload_needed")):
        return (
            "For your safety, this upload cannot be used as-is. "
            "Please upload a new, unedited photo without QR codes, overlays, or embedded instructions."
        )
    if bool(actions.get("captcha_required")):
        return "High-risk upload pattern detected. Please verify by replying with `captcha: <token>`."
    if bool(actions.get("auth_stepup_required")):
        return "Additional verification required. Reply with `stepup: <token>` to continue."
    if verdict in {"escalate", "block"}:
        return "This upload pattern was escalated for security review."
    return None


async def _run_security_sidecar(
    *,
    redis_client: Any,
    blob: bytes,
    filename: str,
    query: str,
    uid: str,
    source_ip: str,
    captcha_token: str | None,
    mfa_stepup_token: str | None,
    features_task: "asyncio.Task[Dict[str, Any]]",
    ingest_gate: Dict[str, Any],
) -> Dict[str, Any]:
    qr_task = asyncio.create_task(asyncio.to_thread(_qr_decode_signals, filename, blob))
    img_sec_task = asyncio.create_task(asyncio.to_thread(_adversarial_and_steg, blob))
    features = await features_task
    qr = await qr_task
    img_sec = await img_sec_task

    labels = [str(x) for x in (features.get("labels") or [])[:12]]
    ocr_text = str(features.get("ocr_text") or "")[:1200]
    qr_text = " ".join(str((c or {}).get("data") or "") for c in (qr.get("codes") or [])[:6])
    merged_text = " ".join([str(query or ""), ocr_text, qr_text, " ".join(labels)]).strip()

    prompt_scan: Dict[str, Any] = {}
    try:
        prompt_scan = analyze_payload({"query": merged_text, "source": "image_sidecar_merged"})
    except Exception:
        prompt_scan = {}

    geo = enrich_ip(source_ip or None) or {}
    asn_val = geo.get("asn")
    asn = int(asn_val) if isinstance(asn_val, int) else None
    abuse = evaluate_behavioral_upload_abuse(
        redis_client,
        uid=uid,
        source_ip=source_ip,
        asn=asn,
        image_hash=str(features.get("image_hash") or ""),
        session_id=f"{uid}:{source_ip}",
        captcha_token=captcha_token,
        mfa_stepup_token=mfa_stepup_token,
    )

    verdict = str(abuse.get("verdict") or "allow")
    reasons: List[str] = [str(abuse.get("reason") or "")]

    actions = dict((abuse.get("actions") or {}))
    actions.setdefault("reupload_needed", False)

    signals: Dict[str, Any] = {}
    signals.update(abuse.get("signals") or {})
    signals.update(
        {
            "qr_code_detected": bool(qr.get("qr_code_detected")),
            "qr_prompt_injection": bool(qr.get("qr_prompt_injection")),
            "qr_external_url": bool(qr.get("qr_external_url")),
            "adversarial_detected": bool(img_sec.get("adversarial_detected")),
            "adversarial_score": float(img_sec.get("adversarial_score") or 0.0),
            "diffusion_score": float(img_sec.get("diffusion_score") or 0.0),
            "steg_suspicious": bool(img_sec.get("steg_suspicious")),
            "steg_score": float(img_sec.get("steg_score") or 0.0),
            "cross_modal_prompt_injection": bool((prompt_scan.get("signals") or {}).get("prompt_injection")),
        }
    )

    if bool(ingest_gate.get("blocked")):
        verdict = _raise_verdict(verdict, "block")
        actions["reupload_needed"] = True
        reasons.append("strict_ingest_blocked")

    if bool(qr.get("qr_prompt_injection")) or bool(qr.get("qr_external_url")):
        verdict = _raise_verdict(verdict, "challenge")
        actions["reupload_needed"] = True
        reasons.append("qr_security_violation")

    if bool(img_sec.get("adversarial_detected")) or bool(img_sec.get("steg_suspicious")):
        verdict = _raise_verdict(verdict, "challenge")
        reasons.append("image_adversarial_or_steg")
        if bool(img_sec.get("adversarial_detected")) and bool(img_sec.get("steg_suspicious")):
            verdict = _raise_verdict(verdict, "escalate")

    prompt_sev = str(prompt_scan.get("severity") or "").lower()
    if prompt_sev in {"high", "critical"}:
        verdict = _raise_verdict(verdict, "escalate")
        reasons.append("cross_modal_injection_risk")

    if verdict in {"escalate", "block"}:
        actions["soc_escalate"] = True
    else:
        actions["soc_escalate"] = bool(actions.get("soc_escalate"))

    # Respect challenge pass: if behavioral detector indicates challenge passed and
    # only behavioral challenge was active, keep current verdict.
    if verdict == "challenge":
        ch = abuse.get("challenge") or {}
        if bool(ch.get("satisfied")) and not actions.get("reupload_needed"):
            verdict = "allow"

    score = max(
        float(abuse.get("risk_score") or 0.0),
        float(img_sec.get("adversarial_score") or 0.0),
        float(img_sec.get("steg_score") or 0.0),
    )
    if verdict in {"escalate", "block"}:
        score = max(score, 0.85)
    elif verdict == "challenge":
        score = max(score, 0.55)

    return {
        "verdict": verdict,
        "reason": ",".join([r for r in reasons if r]) or "security_sidecar",
        "risk_score": round(min(1.0, max(0.0, score)), 4),
        "signals": signals,
        "actions": actions,
        "message": _security_message(verdict=verdict, actions=actions),
        "challenge": abuse.get("challenge") or {},
        "geo": {
            "asn": asn,
            "country": geo.get("country"),
            "asn_org": geo.get("asn_org"),
            "risk": float(geo.get("risk") or 0.0),
        },
    }


async def _run_intent_sidecar(
    *,
    query: str,
    recent_messages: List[Dict[str, Any]],
    features_task: "asyncio.Task[Dict[str, Any]]",
) -> Dict[str, Any]:
    features = await features_task
    labels = [str(x) for x in (features.get("labels") or [])[:12]]
    intent = classify_image_intent(
        image_labels=labels,
        image_ocr_text=str(features.get("ocr_text") or "")[:800],
        damage_score=float(features.get("damage_score") or 0.0),
        is_product_photo=bool(features.get("is_product_photo")),
        user_query=query,
        recent_messages=recent_messages or [],
    )
    route = str(intent.get("intent") or "disambiguate")
    return {
        "intent_route": route,
        "intent_result": intent,
        "context": {
            "labels": labels,
            "ocr_text": str(features.get("ocr_text") or "")[:800],
            "image_hash": str(features.get("image_hash") or ""),
            "damage_score": float(features.get("damage_score") or 0.0),
            "is_product_photo": bool(features.get("is_product_photo")),
            "analysis": features.get("analysis") or {},
            "provider": features.get("provider"),
        },
    }


def _merge_sidecars(security: Dict[str, Any], intent: Dict[str, Any]) -> Dict[str, Any]:
    actions = security.get("actions") or {}
    sec_verdict = str(security.get("verdict") or "allow")
    intent_route = str(intent.get("intent_route") or "disambiguate")

    merged_route = intent_route
    if bool(actions.get("reupload_needed")):
        merged_route = "reupload"
    elif sec_verdict in {"escalate", "block"}:
        merged_route = "security_escalation"
    elif sec_verdict == "challenge" and (bool(actions.get("captcha_required")) or bool(actions.get("auth_stepup_required"))):
        merged_route = "security_challenge"

    message = security.get("message")
    if not message:
        if merged_route == "cv_triage":
            message = "Image routed to return/warranty triage."
        elif merged_route == "visual_search":
            message = "Image routed to visual similarity search."
        elif merged_route == "disambiguate":
            message = (
                "I see the photo. Reply with `find similar` for visual search or "
                "`report issue` for return/complaint triage."
            )

    return {
        "route": merged_route,
        "security_verdict": sec_verdict,
        "intent_route": intent_route,
        "message": message,
    }


@router.post("/route")
async def route_image_with_sidecars(
    request: Request,
    image: UploadFile = File(...),
    query: str = Form(default=""),
    uid: str = Form(default="demo-user"),
    session_id: str | None = Form(default=None),
    captcha_token: str | None = Form(default=None),
    mfa_stepup_token: str | None = Form(default=None),
    recent_messages_json: str | None = Form(default=None),
    redis_client: Any = Depends(get_redis),
    role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    if image is None:
        raise HTTPException(status_code=400, detail="image_required")

    blob = await image.read()
    if not blob:
        raise HTTPException(status_code=400, detail="empty_image")

    filename = str(image.filename or "upload.jpg")
    content_type = str(image.content_type or "")
    trace_id = f"img-sidecar-{uuid.uuid4()}"
    source_ip = (request.client.host if request and request.client else None) or "unknown"

    ingest_gate = strict_image_ingest_gate(filename=filename, content_type=content_type, blob=blob, size_bytes=len(blob))
    if bool(ingest_gate.get("blocked")):
        blocked_resp = {
            "decision_trace_id": trace_id,
            "route": "reupload",
            "security_verdict": "block",
            "intent_route": "disambiguate",
            "message": "Upload blocked by strict ingest gate. Please provide a different image.",
            "security": {
                "verdict": "block",
                "reason": "strict_ingest_blocked",
                "actions": {"reupload_needed": True, "captcha_required": False, "auth_stepup_required": False, "soc_escalate": False},
                "signals": {"strict_ingest_blocked": True, "ingest_block_reasons": ingest_gate.get("block_reasons") or []},
                "risk_score": 0.95,
                "challenge": {"required": False, "satisfied": False, "mode": None, "reason": None},
            },
            "intent": {"intent_route": "disambiguate", "intent_result": {"intent": "disambiguate", "confidence": 0.0}},
            "context": {"labels": [], "ocr_text": "", "image_hash": hashlib.sha256(blob).hexdigest()[:32]},
            "ingest_gate": ingest_gate,
        }
        try:
            emit_security_event(
                "/api/v1/vision/route",
                {
                    "payload": {"uid": uid, "ip": source_ip, "query": query, "cv_signals": blocked_resp["security"]["signals"]},
                    "analysis": {
                        "severity": "high",
                        "risk_raw": 95.0,
                        "risk_adj": 95.0,
                        "signals": blocked_resp["security"]["signals"],
                    },
                },
                request=request,
            )
        except Exception:
            pass
        return blocked_resp

    recent_messages: List[Dict[str, Any]] = []
    if isinstance(recent_messages_json, str) and recent_messages_json.strip():
        try:
            parsed = json.loads(recent_messages_json)
            if isinstance(parsed, list):
                recent_messages = [x for x in parsed if isinstance(x, dict)][:6]
        except Exception:
            recent_messages = []

    # Optional tenant-level storage policy hint from security_event_ingest config.
    tenant_id = str((request.headers.get("x-tenant-id") if request else "") or "").strip() or None
    storage_policy = _tenant_cfg_store.get_override("security_event_storage_policy", tenant_id=tenant_id) or {}

    features_task = asyncio.create_task(_extract_image_features(blob, filename))
    security_task = asyncio.create_task(
        _run_security_sidecar(
            redis_client=redis_client,
            blob=blob,
            filename=filename,
            query=query,
            uid=uid,
            source_ip=source_ip,
            captcha_token=captcha_token,
            mfa_stepup_token=mfa_stepup_token,
            features_task=features_task,
            ingest_gate=ingest_gate,
        )
    )
    intent_task = asyncio.create_task(
        _run_intent_sidecar(
            query=query,
            recent_messages=recent_messages,
            features_task=features_task,
        )
    )

    security, intent = await asyncio.gather(security_task, intent_task)
    merged = _merge_sidecars(security, intent)

    severity = "info"
    if merged["security_verdict"] in {"challenge"}:
        severity = "medium"
    if merged["security_verdict"] in {"escalate", "block"}:
        severity = "high"

    try:
        emit_security_event(
            "/api/v1/vision/route",
            {
                "payload": {
                    "uid": uid,
                    "ip": source_ip,
                    "query": query,
                    "cv_signals": security.get("signals") or {},
                    "route": merged.get("route"),
                    "intent_route": merged.get("intent_route"),
                },
                "analysis": {
                    "severity": severity,
                    "risk_raw": float(security.get("risk_score") or 0.0) * 100.0,
                    "risk_adj": float(security.get("risk_score") or 0.0) * 100.0,
                    "signals": security.get("signals") or {},
                },
            },
            request=request,
        )
    except Exception:
        pass

    try:
        from src.app.services.decision_log import log_trace_event

        log_trace_event(
            trace_id=trace_id,
            event_type="image_sidecar_merge",
            source_type="agent",
            source_id="Image_Sidecar_Coordinator",
            target_type="router",
            target_id="/api/v1/vision/route",
            payload={
                "security_verdict": merged.get("security_verdict"),
                "intent_route": merged.get("intent_route"),
                "route": merged.get("route"),
                "risk_score": security.get("risk_score"),
            },
        )
    except Exception:
        pass

    return {
        "decision_trace_id": trace_id,
        "route": merged.get("route"),
        "security_verdict": merged.get("security_verdict"),
        "intent_route": merged.get("intent_route"),
        "message": merged.get("message"),
        "security": security,
        "intent": intent,
        "context": intent.get("context") or {},
        "ingest_gate": ingest_gate,
        "tenant_storage_policy": storage_policy,
        "session_id": str(session_id or ""),
    }

