from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from typing import Any, Dict, List, Optional
import time
import base64
import io

from src.app.security.auth import require_role, ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER
from src.app.services.cv_triage_basic import BasicCVTriage
from src.app.services.cv_tiered import TieredCVProvider
from src.app.services.cv_evidence import persist_cv_analysis, build_evidence_bundle, persist_evidence_bundle
from src.app.services.decision_log import log_trace_event, log_decision
from src.app.services.cv_warmup import warmup_cv_models
from fastapi import UploadFile, File
from src.app.services.cv_tier2_pipeline import run_tier2
from src.app.services.storage_s3 import get_default_storage
import os
import uuid
from src.app.services.forensics_policy import evaluate as evaluate_forensics_policy
from src.app.services.image_forensics import ImageForensicsService
from src.app.services.agent_bus import AgentBus
from src.app.services.agent_handoff import AgentHandoff
from src.app.deps import get_redis
from src.app.services.tenant_quota import TenantQuotaGuard
from src.app.policy.vertical_pack import load_vertical_pack, resolve_pack_id
from src.app.rules.image_quality import assess_image_quality
from src.app.services.dependency_resilience import call_with_resilience
from src.app.models.db import db_session
from sqlalchemy import text as sql_text
from src.app.services.intake_gate import strict_binary_ingest_gate


router = APIRouter(prefix="/api/v1/cv", tags=["cv"])


def _normalize_upload_for_cv(
    *, filename: str | None, content_type: str | None, blob: bytes
) -> tuple[bytes, str | None, str, Dict[str, Any]]:
    """Convert supported document uploads (PDF) into an image for CV processing.

    Returns: (normalized_blob, normalized_content_type, normalized_filename, metadata)
    """
    safe_name = str(filename or "upload")
    ctype = str(content_type or "").lower().strip()
    is_pdf = ctype == "application/pdf" or safe_name.lower().endswith(".pdf")
    if not is_pdf:
        return blob, content_type, safe_name, {}

    meta: Dict[str, Any] = {"source_document": "pdf"}
    try:
        import pypdfium2 as pdfium

        pdf = pdfium.PdfDocument(blob)
        meta["pdf_pages"] = len(pdf)
        if len(pdf) < 1:
            raise ValueError("empty_pdf")

        page = pdf[0]
        bitmap = page.render(scale=2.0)
        pil_image = bitmap.to_pil()
        out = io.BytesIO()
        pil_image.save(out, format="PNG")
        png = out.getvalue()
        normalized_name = f"{safe_name.rsplit('.', 1)[0]}_page1.png"
        meta["normalized_from_pdf"] = True
        return png, "image/png", normalized_name, meta
    except Exception as exc:
        raise ValueError(f"pdf_conversion_failed:{str(exc)[:160]}")


class CVAnalyzeRequest(BaseModel):
    case_id: Optional[str] = None
    order_id: Optional[str] = None
    labels: List[str] = []
    extracted_text: Optional[str] = None
    provider: str = "basic"
    model: str = "cv_triage_basic"
    images: Optional[List[Dict[str, Any]]] = None  # sanitized image metadata (mime, size, sha256, phash)
    images_b64: Optional[List[str]] = None  # optional raw images for real analysis (base64 or data: URLs)
    description: Optional[str] = None
    issue_type: Optional[str] = None


@router.post("/analyze")
async def analyze(
    req: CVAnalyzeRequest,
    request: Any = None,
    role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    """Analyze complaint images/text and persist CV evidence bundle.

    Accepts sanitized image metadata, labels, and extracted text; returns analysis summary
    and an evidence bundle id when persistence succeeds.
    """
    try:
        try:
            quota = TenantQuotaGuard(get_redis())
            allowed, qmeta = quota.check_and_consume(req.case_id or "global", "cv_calls", amount=1)
            if not allowed:
                raise HTTPException(status_code=429, detail={"error": "tenant_quota_exceeded", **qmeta})
        except HTTPException:
            raise
        except Exception:
            pass
        # Optional async offload to worker queue for autoscaled CV processing.
        try:
            if str(__import__("os").getenv("CV_ASYNC_QUEUE_ENABLED", "0")).strip().lower() in ("1", "true", "yes"):
                from src.app.workers.rq_queue import enqueue_cv

                job_id = enqueue_cv(
                    {
                        "case_id": req.case_id,
                        "images": req.images or [],
                        "labels": req.labels or [],
                        "extracted_text": req.extracted_text or "",
                        "provider": req.provider,
                        "model": req.model,
                    }
                )
                if job_id:
                    return {
                        "status": "accepted",
                        "queued": True,
                        "job_id": job_id,
                        "case_id": req.case_id,
                    }
        except Exception:
            pass
        # If raw images are provided, do real CV/OCR + consistency checks.
        # Otherwise, this endpoint is metadata-only and cannot validate mismatched images.
        sanitized_images: List[Dict[str, Any]] = []
        image_consistency: Optional[Dict[str, Any]] = None
        qr_decode_hits: List[Dict[str, Any]] = []
        qr_prompt_injection = False
        labels = list(req.labels or [])
        extracted_text = (req.extracted_text or "") if req.extracted_text is not None else ""

        if req.images_b64:
            try:
                from src.app.services.image_intake import sanitize_image

                for idx, b64 in enumerate((req.images_b64 or [])[:8]):
                    s = (b64 or "").strip()
                    if not s:
                        continue
                    # Support both plain base64 strings and data URLs.
                    if s.startswith("data:") and "," in s:
                        s = s.split(",", 1)[1]
                    try:
                        content = base64.b64decode(s, validate=False)
                    except Exception:
                        content = b""
                    gate = strict_binary_ingest_gate(
                        filename=f"analyze_{idx + 1}.jpg",
                        content_type=None,
                        blob=content,
                        size_bytes=len(content),
                    )
                    if bool(gate.get("blocked")):
                        raise HTTPException(
                            status_code=400,
                            detail={
                                "error": "ingest_gate_blocked",
                                "message": "One or more uploaded images failed strict ingest checks.",
                                "ingest_gate": gate,
                            },
                        )
                    meta = sanitize_image(content)
                    try:
                        meta["filename"] = f"analyze_{idx + 1}.jpg"
                    except Exception:
                        pass
                    sanitized_images.append(meta)
            except Exception:
                sanitized_images = []

            # OCR/labels from the first sanitized image (best-effort).
            try:
                if sanitized_images and str(sanitized_images[0].get("status") or "") == "sanitized":
                    from src.app.services.cv_provider import ManagedCVProvider

                    labels, extracted_text = await ManagedCVProvider().get_labels_and_text(
                        sanitized_images[0].get("bytes") or b""
                    )
            except Exception:
                pass

            # Image consistency (mismatch, suspicious overlays, low evidence).
            try:
                # Import locally to avoid heavy import/cycle at module load time.
                from src.app.routers.support_complaints import _evaluate_uploaded_images_consistency

                image_consistency = await _evaluate_uploaded_images_consistency(
                    sanitized_images=sanitized_images,
                    description=req.description,
                    issue_type=req.issue_type,
                    order_id=req.order_id,
                )
            except Exception:
                image_consistency = None

            # Barcode/QR payload scan (best-effort) to catch encoded prompt-injection text.
            try:
                from src.app.rules.barcode_decode import decode_barcodes
                from src.app.routers.support_complaints import _detect_ocr_prompt_injection  # type: ignore

                qr = decode_barcodes(
                    [
                        (str(s.get("filename") or f"img_{i + 1}.jpg"), s.get("bytes") or b"")
                        for i, s in enumerate(sanitized_images or [])
                        if str(s.get("status") or "") == "sanitized"
                    ]
                )
                qr_decode_hits = qr.codes or []
                qr_decode_reasons = getattr(qr, "reasons", []) or []
                for c in qr_decode_hits:
                    if _detect_ocr_prompt_injection(str(c.get("data") or "")):
                        qr_prompt_injection = True
                        break
            except Exception:
                qr_decode_hits = []
                qr_prompt_injection = False

            # Fold QR findings into image-consistency UX so the buyer is prompted to reupload
            # unedited photos without codes/overlays (mirrors support_complaints behavior).
            try:
                qr_external_url = False
                if qr_decode_hits:
                    try:
                        from urllib.parse import urlparse
                        allow_hosts = {"127.0.0.1", "localhost"}
                        for c in qr_decode_hits:
                            data = str(c.get("data") or "").strip()
                            if data.lower().startswith(("http://", "https://")):
                                host = (urlparse(data).hostname or "").lower()
                                if host and host not in allow_hosts:
                                    qr_external_url = True
                                    break
                    except Exception:
                        qr_external_url = False

                if isinstance(image_consistency, dict) and isinstance(image_consistency.get("images"), list) and qr_decode_hits:
                    images_out = image_consistency.get("images") or []
                    qr_files = set()
                    try:
                        for c in qr_decode_hits:
                            fn = str(c.get("filename") or "").strip()
                            if fn:
                                qr_files.add(fn)
                    except Exception:
                        qr_files = set()
                    # Tag all matching images (by filename). Fall back to index 0 if filenames are missing.
                    tagged_any = False
                    for im in images_out:
                        try:
                            fn = str(im.get("filename") or "").strip()
                        except Exception:
                            fn = ""
                        match = False
                        if qr_files and fn and fn in qr_files:
                            match = True
                        if not qr_files:
                            try:
                                match = int(im.get("index", -1)) == 0
                            except Exception:
                                match = False
                        if not match:
                            continue
                        reasons = im.get("reasons")
                        if not isinstance(reasons, list):
                            reasons = []
                        if "qr_code_detected" not in reasons:
                            reasons.append("qr_code_detected")
                        if qr_external_url and "qr_external_url_detected" not in reasons:
                            reasons.append("qr_external_url_detected")
                        if qr_prompt_injection and "qr_prompt_injection" not in reasons:
                            reasons.append("qr_prompt_injection")
                        im["reasons"] = reasons[:6]
                        if str(im.get("status") or "match") == "match":
                            im["status"] = "suspicious"
                        tagged_any = True
                    if not tagged_any and images_out:
                        try:
                            im = images_out[0]
                            reasons = im.get("reasons")
                            if not isinstance(reasons, list):
                                reasons = []
                            if "qr_code_detected" not in reasons:
                                reasons.append("qr_code_detected")
                            if qr_external_url and "qr_external_url_detected" not in reasons:
                                reasons.append("qr_external_url_detected")
                            if qr_prompt_injection and "qr_prompt_injection" not in reasons:
                                reasons.append("qr_prompt_injection")
                            im["reasons"] = reasons[:6]
                            if str(im.get("status") or "match") == "match":
                                im["status"] = "suspicious"
                        except Exception:
                            pass

                    mismatch_count = 0
                    needs_better_count = 0
                    suspicious_count = 0
                    for im in images_out:
                        st = str(im.get("status") or "").lower()
                        if st in ("mismatch", "suspicious"):
                            mismatch_count += 1
                        if st == "needs_better_image":
                            needs_better_count += 1
                        if st == "suspicious":
                            suspicious_count += 1
                    image_consistency["mismatch_count"] = mismatch_count
                    image_consistency["needs_better_count"] = needs_better_count
                    image_consistency["suspicious_count"] = suspicious_count
                    image_consistency["status"] = "mismatch" if mismatch_count > 0 else ("needs_better_image" if needs_better_count > 0 else "match")
                    image_consistency["soft_verify_required"] = bool(image_consistency["status"] in ("mismatch", "needs_better_image"))
                    image_consistency["prompt"] = (
                        "For your security, we can't accept photos that include QR codes or external links. "
                        "Please upload a new, unedited photo of the item and the damaged area (no stickers, overlays, or QR codes)."
                        if qr_external_url
                        else "For your security, please reupload a new, unedited photo without any QR codes or overlays."
                    )
            except Exception:
                pass
        # Security observer scan for CV evidence (DREAD/STRIDE/PASTA/OWASP etc.) for Decision Trace Security Matrix.
        security_details = {}
        security_sev = None
        try:
            from src.app.security.observer import analyze_payload, emit_security_event

            ic_status = (image_consistency or {}).get("status") if isinstance(image_consistency, dict) else None
            cv_signals = {
                "qr_code_detected": bool(qr_decode_hits),
                "qr_prompt_injection": bool(qr_prompt_injection),
                "image_consistency_mismatch": bool(ic_status in ("mismatch", "suspicious")),
                "ocr_prompt_injection": bool((image_consistency or {}).get("ocr_prompt_injection")) if isinstance(image_consistency, dict) else False,
            }
            security_payload = {
                "description": req.description,
                "issue_type": req.issue_type,
                "ocr_text": extracted_text,
                "labels": labels,
                "image_consistency": image_consistency,
                "qr_codes": qr_decode_hits,
                "diagnostics": {"qr_decoder": qr_decode_reasons if 'qr_decode_reasons' in locals() else []},
                "cv_signals": cv_signals,
                "endpoint": "/api/v1/cv/analyze",
            }
            analysis = analyze_payload(security_payload)
            security_details = analysis.get("details") or {}
            security_sev = analysis.get("severity")
            try:
                emit_security_event("/api/v1/cv/analyze", {"payload": security_payload, "analysis": security_details}, request=request)
            except Exception:
                pass
        except Exception:
            security_details = {}
            security_sev = None

        started = time.time()
        triage = BasicCVTriage()
        res = triage.analyze(labels=labels or [], extracted_text=extracted_text or "")
        try:
            import inspect as _inspect

            analysis = await res if _inspect.isawaitable(res) else res
        except Exception:
            analysis = res
        processing_ms = int((time.time() - started) * 1000)

        case_id = req.case_id or __import__("uuid").uuid4().hex
        try:
            persist_cv_analysis(
                case_id=case_id,
                image_sha256=None,
                image_phash=None,
                analysis=analysis,
                labels=labels or [],
                extracted_text=extracted_text or "",
                provider=req.provider,
                model=req.model,
                processing_time_ms=processing_ms,
            )
        except Exception:
            pass

        # Build and persist evidence bundle
        bundle = build_evidence_bundle(
            case_id=case_id,
            sanitized_images=(sanitized_images if sanitized_images else (req.images or [])),
            labels=labels or [],
            extracted_text=extracted_text or "",
            analysis=analysis,
            reverse_hits=[],
            provider=req.provider,
            model=req.model,
            processing_time_ms=processing_ms,
            sanitize_time_ms=None,
            fraud={},
            trust={},
            issue_type=req.issue_type,
            description=req.description,
        )
        try:
            if image_consistency is not None:
                bundle["image_consistency"] = image_consistency
            if qr_decode_hits:
                bundle["qr_codes"] = qr_decode_hits[:10]
            if qr_prompt_injection:
                bundle["qr_prompt_injection"] = True
        except Exception:
            pass
        evidence_id = persist_evidence_bundle(case_id, bundle)

        # Attach decision trace event best-effort
        try:
            log_trace_event(
                trace_id=case_id,
                event_type="cv_analyze",
                source_type="agent",
                source_id="cv_basic",
                target_type="complaint",
                target_id=case_id,
                payload={
                    "analysis": analysis,
                    "evidence_id": evidence_id,
                    "processing_ms": processing_ms,
                    "image_consistency": image_consistency,
                    "qr_prompt_injection": qr_prompt_injection,
                },
            )
        except Exception:
            pass

        # Emit security_scan trace event for Decision Trace Security Matrix.
        # Always emit this event so the matrix panel can render even for benign lanes.
        try:
            sec_signals = {}
            if isinstance(security_details, dict):
                for k, v in (security_details.get("signals") or {}).items():
                    if isinstance(v, bool):
                        sec_signals[str(k)] = v
                for k, v in security_details.items():
                    if isinstance(v, bool):
                        sec_signals[str(k)] = v
            if qr_prompt_injection:
                sec_signals["qr_prompt_injection"] = True
            if qr_decode_hits:
                sec_signals["qr_code_detected"] = True
            ic_status = (image_consistency or {}).get("status") if isinstance(image_consistency, dict) else None
            if ic_status in ("mismatch", "suspicious"):
                sec_signals["image_consistency_mismatch"] = True
            if isinstance(image_consistency, dict) and bool(image_consistency.get("ocr_prompt_injection")):
                sec_signals["ocr_prompt_injection"] = True

            sev = str(security_sev or ("high" if qr_prompt_injection else ("warn" if sec_signals else "info"))).lower()
            if sev in ("critical", "high", "error"):
                route = "escalate"
            elif sev in ("warn", "warning", "medium") or sec_signals:
                route = "review"
            else:
                route = "allow"

            details_payload = dict(security_details or {}) if isinstance(security_details, dict) else {}
            details_payload["signals"] = {**(details_payload.get("signals") or {}), **sec_signals}

            payload = {
                "details": details_payload,
                "severity": sev,
                "route": route,
                "threshold_version": os.getenv("SECURITY_THRESHOLD_VERSION", "security-v1"),
                "ocr_text": (extracted_text or "")[:2000],
                "entities": {"labels": (labels or [])[:20], "qr_code_count": len(qr_decode_hits or [])},
            }
            if 'qr_decode_reasons' in locals():
                payload["diagnostics"] = {"qr_decoder": qr_decode_reasons}
            log_trace_event(
                trace_id=case_id,
                event_type="security_scan",
                source_type="agent",
                source_id="Security_Observer_Agent",
                target_type="complaint",
                target_id=case_id,
                payload=payload,
            )
        except Exception:
            pass

        # Persist a decision log for analyze path so UI always has a trace id.
        # Approval is required when signals suggest human intervention (QR/prompt injection or mismatch/suspicious).
        try:
            verdict = (analysis or {}).get("verdict") or {}
            required_actions = verdict.get("required_actions") or []
            ic_status = (image_consistency or {}).get("status") if isinstance(image_consistency, dict) else None
            approval_actions = {"human_review", "manual_approval", "policy_escalation"}
            signal_review = bool(qr_prompt_injection or (ic_status in ("mismatch", "suspicious")))
            approval_required = signal_review or any(a in approval_actions for a in required_actions)
            exec_status = "review_required" if approval_required else "completed"
            try:
                # Derive minimal proposed actions when signals are present
                derived_actions = list(required_actions)
                if signal_review and "human_review" not in derived_actions:
                    derived_actions.append("human_review")
                if ic_status == "needs_better_image" and "needs_better_image" not in derived_actions:
                    derived_actions.append("needs_better_image")
                input_payload = {"case_id": case_id, "extract_sample": (req.extracted_text or "")[:1024]}
                retrieved_context = {"cv_analysis": analysis, "evidence_id": evidence_id}
                proposed_action = {"required_actions": derived_actions[:6], "verdict": verdict}
                log_decision(
                    agent_name="cv_forensics",
                    input_data=input_payload,
                    retrieved_context=retrieved_context,
                    proposed_action=proposed_action,
                    policy_version="v1",
                    approval_required=approval_required,
                    execution_status=exec_status,
                    decision_id=case_id,
                )
            except Exception:
                pass
        except Exception:
            pass

        # Derive ui_actions based on evidence signals
        qr_external_url_detected = False
        try:
            imgs = (image_consistency or {}).get("images") if isinstance(image_consistency, dict) else []
            for im in imgs or []:
                reasons = im.get("reasons") if isinstance(im, dict) else []
                if isinstance(reasons, list) and "qr_external_url_detected" in reasons:
                    qr_external_url_detected = True
                    break
        except Exception:
            qr_external_url_detected = False
        _needs_chat = bool(
            qr_prompt_injection
            or qr_external_url_detected
            or (isinstance(image_consistency, dict) and image_consistency.get("status") in ("mismatch", "suspicious"))
        )

        return {
            "status": "ok",
            "case_id": case_id,
            "cv_analysis": analysis,
            "evidence_id": evidence_id,
            "trace_id": case_id,
            "image_consistency": image_consistency,
            "qr_codes": qr_decode_hits[:10],
            "qr_prompt_injection": qr_prompt_injection,
            "ui_actions": {"chat_with_admin": _needs_chat},
            "suggested_routing": "security_review" if _needs_chat else "standard_queue",
        }
    except HTTPException:
        raise
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception:
        raise HTTPException(status_code=500, detail="cv analyze failed")


@router.post("/warmup")
def warmup(role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER]))) -> Dict[str, Any]:
    """Warm up CV dependencies (YOLO/CLIP/OCR)."""
    try:
        return {"status": "ok", "warmup": warmup_cv_models()}
    except Exception:
        raise HTTPException(status_code=500, detail="cv warmup failed")


_NONCE_STORE: dict[str, float] = {}


@router.get("/nonce")
def issue_nonce(role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER]))) -> Dict[str, Any]:
    import time, uuid
    n = uuid.uuid4().hex[:8]
    _NONCE_STORE[n] = time.time()
    return {"nonce": n, "expires_in": 300}


@router.post("/upload")
async def upload(
    image: UploadFile = File(...),
    nonce: str | None = None,
    order_id: str | None = Query(default=None),
    customer_id: str | None = Query(default=None),
    guest_email: str | None = Query(default=None),
    sku: str | None = Query(default=None),
    expected_label: str | None = Query(default=None),
    issue_type: str | None = Query(default=None),
    description: str | None = Query(default=None),
    role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    """Upload an image, run Tier 2 CV including forensics verdict, and return a decision hint.

    If `nonce` is provided, it is checked for recent issuance (best-effort).
    """
    fallback_case_id = uuid.uuid4().hex
    try:
        try:
            quota = TenantQuotaGuard(get_redis())
            allowed, qmeta = quota.check_and_consume("global", "cv_calls", amount=1)
            if not allowed:
                raise HTTPException(status_code=429, detail={"error": "tenant_quota_exceeded", **qmeta})
        except HTTPException:
            raise
        except Exception:
            pass
        content = await image.read()
        normalized_meta: Dict[str, Any] = {}
        try:
            content, normalized_content_type, normalized_filename, normalized_meta = _normalize_upload_for_cv(
                filename=image.filename,
                content_type=image.content_type,
                blob=content,
            )
        except ValueError as ve:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "document_conversion_failed",
                    "message": "Unable to convert uploaded document into an analyzable image.",
                    "detail": str(ve),
                },
            )
        # Always allocate a unique case id for this upload so evidence/decisions don't collide on filename.
        case_id = uuid.uuid4().hex or fallback_case_id
        gate = strict_binary_ingest_gate(
            filename=str(image.filename or "upload"),
            content_type=image.content_type,
            blob=content,
            size_bytes=len(content),
        )
        if bool(gate.get("blocked")):
            try:
                log_trace_event(
                    trace_id=case_id,
                    event_type="security_scan",
                    source_type="agent",
                    source_id="intake_gate",
                    target_type="complaint",
                    target_id=case_id,
                    payload={
                        "severity": "high",
                        "route": "escalate",
                        "details": {"signals": {"ingest_gate_blocked": True}, "ingest_gate": gate},
                    },
                )
            except Exception:
                pass
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "ingest_gate_blocked",
                    "message": "Upload blocked by strict ingest gate (type/size/archive/AV policy).",
                    "ingest_gate": gate,
                },
            )

        order_ctx = None
        if order_id:
            try:
                with db_session() as db:
                    row = db.execute(
                        sql_text("SELECT id, customer_id, guest_email, status, total_cents, created_at FROM orders WHERE id = :id LIMIT 1"),
                        {"id": order_id},
                    ).fetchone()
                if row:
                    order_ctx = {
                        "found": True,
                        "id": row[0],
                        "customer_id": row[1],
                        "guest_email": row[2],
                        "status": row[3],
                        "total_cents": row[4],
                        "created_at": str(row[5]),
                    }
                else:
                    order_ctx = {"found": False, "id": order_id}
            except Exception:
                order_ctx = {"found": None, "id": order_id}
        # Enforce ownership when order context exists: require matching customer_id or guest_email.
        try:
            if isinstance(order_ctx, dict) and order_ctx.get("found") is True:
                provided_cust = (customer_id or "").strip()
                provided_guest = str(guest_email or "").strip().lower()
                match_ok = False
                if provided_cust and str(order_ctx.get("customer_id") or "").strip() == provided_cust:
                    match_ok = True
                if provided_guest and str(order_ctx.get("guest_email") or "").strip().lower() == provided_guest:
                    match_ok = True
                if not match_ok:
                    if not provided_cust and not provided_guest:
                        raise HTTPException(status_code=400, detail={"error": "ownership_info_required", "message": "Provide customer_id or guest_email matching order"})
                    raise HTTPException(status_code=403, detail={"error": "ownership_mismatch", "order_id": order_id})
        except HTTPException:
            raise
        except Exception:
            pass
        # Optional per-environment S3 upload: when enabled, store sanitized image and pass URL into pipeline
        storage_url = None
        try:
            use_s3 = str(__import__("os").getenv("USE_S3_UPLOADS", "0")).strip().lower() in ("1", "true", "yes")
        except Exception:
            use_s3 = False
        if use_s3:
            try:
                sanitized = None
                try:
                    sanitized = sanitize_image(content)
                except Exception:
                    sanitized = None
                data_bytes = (sanitized.get("bytes") if isinstance(sanitized, dict) and sanitized.get("bytes") else content)
                # Sanitize filename to prevent unicode/XSS/path traversal issues
                import re as _re
                _safe_name = _re.sub(r"[^\w\-.]", "_", (image.filename or "upload"))[:100]
                key = f"{uuid.uuid4().hex}_{_safe_name}"
                storage = get_default_storage()
                res = storage.upload_bytes(key, data_bytes, content_type=(normalized_content_type or None))
                if isinstance(res, dict) and res.get("ok"):
                    storage_url = res.get("url")
            except Exception:
                storage_url = None
        # Queue-based async processing mode for CV-heavy upload path.
        try:
            if str(__import__("os").getenv("CV_ASYNC_QUEUE_ENABLED", "0")).strip().lower() in ("1", "true", "yes"):
                from src.app.workers.rq_queue import enqueue_cv

                job_id = enqueue_cv(
                    {
                        "images": [content],
                        "filename": normalized_filename,
                        "content_type": normalized_content_type,
                        "storage_url": storage_url,
                    }
                )
                if job_id:
                    return {"status": "accepted", "queued": True, "job_id": job_id}
        except Exception:
            pass
        # Tier0 gate (quality) before running Tier2 pipeline.
        try:
            enabled = str(__import__("os").getenv("TIER0_RULES_ENABLED", "0")).strip().lower() in ("1", "true", "yes")
        except Exception:
            enabled = False
        if enabled:
            try:
                pack = load_vertical_pack(resolve_pack_id())
                iq_min = float(pack.thresholds.get("image_quality_min", 0.6))
            except Exception:
                iq_min = 0.6
            iq = assess_image_quality([(image.filename or "upload", content)], min_quality_score=iq_min)
            if not iq.ok:
                raise HTTPException(status_code=400, detail={"error": "image_quality_failed", "reasons": iq.reasons, "details": iq.details})
        pack_id = None
        # Tier 2 can fail when optional deps (OCR/vision/QR libs) are missing or the
        # Ollama endpoint/model is not available. Degrade gracefully instead of 400'ing.
        try:
            t2 = call_with_resilience(
                "cv.tier2",
                lambda: run_tier2(
                    content,
                    meta={
                        "case_id": case_id,
                        "filename": normalized_filename,
                        "content_type": normalized_content_type,
                        "order_id": order_id,
                        "order_ctx": order_ctx,
                        "sku": sku,
                        "expected_label": expected_label,
                        "issue_type": issue_type,
                        "description": description,
                        "upload_normalization": normalized_meta,
                    },
                    pack_id=pack_id,
                ),
                timeout_s=8.0,
                retries=1,
            )
        except Exception as exc:
            t2 = {
                "trace_id": case_id,
                "case_id": case_id,
                "model_pack": pack_id or "agnostic_v1",
                "evidence_tags": ["tier2_unavailable"],
                "verdict": {
                    "verdict": "request_more_data",
                    "required_actions": ["needs_better_image"],
                    "severity": "warn",
                },
                "security_analysis": {
                    "severity": "warn",
                    "channel": "cv",
                    "signals": {"tier2_unavailable": True},
                    "tags": ["tier2_unavailable"],
                    "reasons": [str(exc)[:160]],
                    "mitre_atlas": [],
                    "mitre_attack": [],
                    "owasp_llm_top10": [],
                    "stride_categories": [],
                    "dread": {"avg": 0.0},
                    "pasta": {"current_stage": "Stage4"},
                },
            }
        # Policy verdict already in t2; attach nonce status and a minimal next-actions hint
        nonce_ok = False
        if nonce and nonce in _NONCE_STORE:
            import time
            nonce_ok = (time.time() - _NONCE_STORE.get(nonce, 0)) <= 300
        # Minimal hints derived from verdict
        verdict = t2.get("verdict") or {}
        actions = verdict.get("required_actions") or []
        trace_id = str(t2.get("trace_id") or t2.get("case_id") or case_id)
        try:
            handoff_needed = any(
                action in {"human_review", "manual_approval", "policy_escalation"}
                for action in actions
            )
            if handoff_needed:
                await AgentHandoff(bus=AgentBus(get_redis())).request_handoff(
                    from_agent="CV_Forensics_Agent",
                    to_agent="Fraud_Review_Agent",
                    reason="cv_forensics_escalation",
                    context={
                        "filename": image.filename,
                        "content_type": image.content_type,
                        "required_actions": actions,
                        "verdict": verdict,
                    },
                    trace_id=trace_id,
                )
        except Exception:
            pass
        if not nonce_ok and "nonce_live_capture" in actions:
            actions.append("get_nonce_and_live_capture")
        # Best-effort persistence and trace for upload path (mirror analyze behavior)
        try:
            case_id = trace_id or case_id or __import__("uuid").uuid4().hex
            try:
                persist_cv_analysis(
                    case_id=case_id,
                    image_sha256=None,
                    image_phash=None,
                    analysis=t2,
                    labels=[],
                    extracted_text="",
                    provider="tier2",
                    model="tier2",
                    processing_time_ms=None,
                )
            except Exception:
                pass
            try:
                bundle = build_evidence_bundle(
                    case_id=case_id,
                    sanitized_images=[],
                    labels=[],
                    extracted_text="",
                    analysis=t2,
                    reverse_hits=[],
                    provider="tier2",
                    model="tier2",
                    processing_time_ms=None,
                    sanitize_time_ms=None,
                    fraud={},
                    trust={},
                    issue_type=None,
                    description=None,
                )
                evidence_id = persist_evidence_bundle(case_id, bundle)
            except Exception:
                evidence_id = None
            try:
                log_trace_event(
                    trace_id=case_id,
                    event_type="cv_upload",
                    source_type="agent",
                    source_id="cv_upload",
                    target_type="complaint",
                    target_id=case_id,
                    payload={"analysis": t2, "evidence_id": evidence_id},
                )
            except Exception:
                pass
            # Emit security_scan trace event for Decision Trace Security Matrix.
            try:
                t2_security = (t2 or {}).get("security_analysis") if isinstance(t2, dict) else {}
                t2_evidence = (t2 or {}).get("evidence_tags") or []
                sec_signals = {}
                if isinstance(t2_security, dict):
                    for k, v in (t2_security.get("signals") or {}).items():
                        if isinstance(v, bool):
                            sec_signals[str(k)] = v
                if t2_evidence:
                    sec_signals["has_evidence_tags"] = True
                    for tag in t2_evidence:
                        t = str(tag or "").strip()
                        if t:
                            sec_signals[f"evidence_{t}"] = True
                sev = str((t2_security or {}).get("severity") or "").lower()
                if not sev:
                    sev = "high" if any(
                        t in t2_evidence for t in ("qr_url_present", "prompt_injection_text_suspected", "manipulation_detected")
                    ) else ("warn" if sec_signals else "info")
                if sev in ("critical", "high", "error"):
                    route = "escalate"
                elif sev in ("warn", "warning", "medium") or sec_signals:
                    route = "review"
                else:
                    route = "allow"
                details_payload = dict(t2_security or {}) if isinstance(t2_security, dict) else {}
                details_payload["signals"] = {**(details_payload.get("signals") or {}), **sec_signals}
                if t2_evidence:
                    details_payload["evidence_tags"] = t2_evidence
                log_trace_event(
                    trace_id=case_id,
                    event_type="security_scan",
                    source_type="agent",
                    source_id="cv_forensics",
                    target_type="complaint",
                    target_id=case_id,
                    payload={
                        "details": details_payload,
                        "severity": sev,
                        "route": route,
                        "threshold_version": os.getenv("SECURITY_THRESHOLD_VERSION", "security-v1"),
                        "entities": {
                            "filename": image.filename,
                            "evidence_tag_count": len(t2_evidence or []),
                        },
                    },
                )
            except Exception:
                pass
            # Persist a decision log for the upload path so the UI always has a trace id to drill into.
            # Approval is required only when actions imply human intervention; otherwise we record as completed.
            try:
                verdict = (t2 or {}).get("verdict") or {}
                required_actions = verdict.get("required_actions") or []
                approval_actions = {"human_review", "manual_approval", "policy_escalation"}
                approval_required = any(a in approval_actions for a in required_actions)
                exec_status = "review_required" if approval_required else "completed"
                try:
                    input_payload = {"case_id": case_id, "filename": image.filename}
                    retrieved_context = {"cv_analysis": t2, "evidence_id": evidence_id}
                    proposed_action = {"required_actions": required_actions, "verdict": verdict}
                    log_decision(
                        agent_name="cv_forensics",
                        input_data=input_payload,
                        retrieved_context=retrieved_context,
                        proposed_action=proposed_action,
                        policy_version="v1",
                        approval_required=approval_required,
                        execution_status=exec_status,
                        decision_id=case_id,
                    )
                except Exception:
                    pass
            except Exception:
                pass
        except Exception:
            pass

        return {
            "status": "ok",
            "case_id": case_id,
            "cv_tier2": t2,
            "nonce_ok": nonce_ok,
            "next_actions": actions[:6],
        }
    except HTTPException:
        raise
    except Exception:
        # Degrade gracefully: this route is a demo/triage path and should not "do nothing"
        # when optional dependencies (vision/OCR/QR libs) or persistence are unavailable.
        import os as _os
        try:
            env = str(_os.getenv("APP_ENV", "")).strip().lower()
        except Exception:
            env = ""
        if env in ("local", "dev", "development"):
            try:
                import traceback as _tb
                _tb.print_exc()
            except Exception:
                pass
            return {
                "status": "ok",
                "case_id": fallback_case_id,
                "cv_tier2": {
                    "trace_id": fallback_case_id,
                    "case_id": fallback_case_id,
                    "model_pack": "agnostic_v1",
                    "evidence_tags": ["tier2_unavailable", "cv_upload_exception"],
                    "verdict": {
                        "verdict": "request_more_data",
                        "required_actions": ["needs_better_image"],
                        "severity": "warn",
                    },
                    "security_analysis": {
                        "severity": "warn",
                        "channel": "cv",
                        "signals": {"cv_upload_exception": True},
                        "tags": ["cv_upload_exception"],
                        "reasons": [],
                        "mitre_atlas": [],
                        "mitre_attack": [],
                        "owasp_llm_top10": [],
                        "stride_categories": [],
                        "dread": {"avg": 0.0},
                        "pasta": {"current_stage": "Stage4"},
                    },
                },
                "nonce_ok": False,
                "next_actions": ["needs_better_image"],
            }
        raise HTTPException(status_code=400, detail="upload failed: processing error")
