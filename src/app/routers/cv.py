from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from typing import Any, Dict, List, Optional
import logging
import time
import base64
import io
import shutil

_log = logging.getLogger("shopsquire.cv")

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
import asyncio as _asyncio
from src.app.models.db import db_session
from sqlalchemy import text as sql_text
from src.app.services.intake_gate import strict_image_ingest_gate
import collections


router = APIRouter(prefix="/api/v1/cv", tags=["cv"])

# ── Progressive escalation: per-session suspicious upload tracker ──
# Key = client identifier (IP or uid hash), value = list of timestamps.
# In production this would use Redis; here we use a bounded in-process dict.
_SESSION_SUSPICIOUS: dict[str, list[float]] = {}
_SESSION_SUSPICIOUS_MAX_KEYS = 2000
_ESCALATION_WINDOW_SEC = 600  # 10 minutes
_ESCALATION_YELLOW = 1  # 1 suspicious upload = monitoring
_ESCALATION_ORANGE = 2  # 2 = admin notified
_ESCALATION_RED = 3     # 3 = session locked, human escalation


def _record_suspicious_upload(client_key: str) -> str:
    """Record a suspicious upload and return the escalation level: green/yellow/orange/red."""
    now = time.time()
    if len(_SESSION_SUSPICIOUS) > _SESSION_SUSPICIOUS_MAX_KEYS:
        # Evict oldest half
        sorted_keys = sorted(_SESSION_SUSPICIOUS, key=lambda k: (_SESSION_SUSPICIOUS[k] or [0])[-1])
        for k in sorted_keys[:len(sorted_keys) // 2]:
            _SESSION_SUSPICIOUS.pop(k, None)
    entries = _SESSION_SUSPICIOUS.get(client_key, [])
    entries = [t for t in entries if now - t < _ESCALATION_WINDOW_SEC]
    entries.append(now)
    _SESSION_SUSPICIOUS[client_key] = entries
    count = len(entries)
    if count >= _ESCALATION_RED:
        return "red"
    if count >= _ESCALATION_ORANGE:
        return "orange"
    if count >= _ESCALATION_YELLOW:
        return "yellow"
    return "green"


def _get_escalation_level(client_key: str) -> str:
    now = time.time()
    entries = _SESSION_SUSPICIOUS.get(client_key, [])
    entries = [t for t in entries if now - t < _ESCALATION_WINDOW_SEC]
    count = len(entries)
    if count >= _ESCALATION_RED:
        return "red"
    if count >= _ESCALATION_ORANGE:
        return "orange"
    if count >= _ESCALATION_YELLOW:
        return "yellow"
    return "green"


def _is_diagnostic_qr_payload(payload: str, *, context_text: str = "") -> bool:
    raw = str(payload or "").strip().lower()
    ctx = str(context_text or "").strip().lower()
    if not raw:
        return False
    ms_diag = (
        "microsoft.com/fwlink" in raw
        or "windows.com/stopcode" in raw
        or "aka.ms/" in raw
    )
    bsod_ctx = any(tok in ctx for tok in ("blue screen", "bsod", "stop code", "windows crash"))
    return bool(ms_diag and bsod_ctx)


def _cv_runtime_readiness() -> Dict[str, Any]:
    tesseract_ok = bool(shutil.which("tesseract"))
    zbar_ok = False
    try:
        from pyzbar.pyzbar import decode as _decode  # type: ignore

        zbar_ok = bool(_decode)
    except Exception:
        zbar_ok = False
    reasons: List[str] = []
    if not tesseract_ok:
        reasons.append("tesseract_binary_missing")
    if not zbar_ok:
        reasons.append("zbar_runtime_missing")
    return {
        "ready": bool(tesseract_ok and zbar_ok),
        "tesseract_ok": tesseract_ok,
        "zbar_ok": zbar_ok,
        "reasons": reasons,
    }


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
        runtime = _cv_runtime_readiness()
        strict_runtime = str(os.getenv("CV_STRICT_RUNTIME_DEPS", "1")).strip().lower() in ("1", "true", "yes", "on")
        if strict_runtime and not bool(runtime.get("ready")):
            raise HTTPException(status_code=503, detail={"error": "cv_runtime_not_ready", "runtime": runtime})
        try:
            quota = TenantQuotaGuard(get_redis())
            allowed, qmeta = quota.check_and_consume(req.case_id or "global", "cv_calls", amount=1)
            if not allowed:
                raise HTTPException(status_code=429, detail={"error": "tenant_quota_exceeded", **qmeta})
        except HTTPException:
            raise
        except Exception as _exc:
            _log.debug("tenant quota check skipped: %s", _exc)
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
        except Exception as _exc:
            _log.warning("CV async queue enqueue failed, falling back to sync: %s", _exc)
        # If raw images are provided, do real CV/OCR + consistency checks.
        # Otherwise, this endpoint is metadata-only and cannot validate mismatched images.
        sanitized_images: List[Dict[str, Any]] = []
        image_consistency: Optional[Dict[str, Any]] = None
        qr_decode_hits: List[Dict[str, Any]] = []
        qr_prompt_injection = False
        diagnostic_qr_count = 0
        tier2_result: Dict[str, Any] = {}
        tier2_evidence_tags: List[str] = []
        tier2_security: Dict[str, Any] = {}
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
                    gate = strict_image_ingest_gate(
                        filename=f"analyze_{idx + 1}",
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
            except HTTPException:
                raise
            except Exception as _exc:
                _log.warning("image sanitization failed: %s", _exc, exc_info=True)
                sanitized_images = []

            # OCR/labels from the first sanitized image (best-effort).
            try:
                if sanitized_images and str(sanitized_images[0].get("status") or "") == "sanitized":
                    from src.app.services.cv_provider import ManagedCVProvider

                    labels, extracted_text = await ManagedCVProvider().get_labels_and_text(
                        sanitized_images[0].get("bytes") or b""
                    )
            except Exception as _cv_exc:
                import logging as _lg
                _lg.getLogger("cv.analyze").warning("ManagedCVProvider failed: %s", _cv_exc, exc_info=True)

            # If ManagedCVProvider yielded no text, try local tesseract directly
            # so downstream security analysis has OCR evidence even when Ollama is down.
            if not extracted_text and sanitized_images and str(sanitized_images[0].get("status") or "") == "sanitized":
                try:
                    from src.app.services.cv_provider import ManagedCVProvider as _MCP
                    _prov = _MCP()
                    extracted_text = _prov._tesseract_text(sanitized_images[0].get("bytes") or b"")
                except Exception as _exc:
                    _log.debug("tesseract fallback failed: %s", _exc)

            # ── Parallelize independent analysis tasks for ~2-3x speedup ──
            # tier2 scan, image consistency, and QR decode are independent once labels/text exist.
            async def _run_tier2_task():
                try:
                    if sanitized_images and str(sanitized_images[0].get("status") or "") == "sanitized":
                        _img0 = sanitized_images[0].get("bytes") or b""
                        if isinstance(_img0, (bytes, bytearray)) and _img0:
                            _meta = {
                                "filename": str(sanitized_images[0].get("filename") or "analyze_1.jpg"),
                                "case_id": str(req.case_id or ""),
                                "description": req.description,
                                "issue_type": req.issue_type,
                                "order_id": req.order_id,
                            }
                            result = await _asyncio.to_thread(
                                run_tier2, bytes(_img0), meta=_meta,
                                pack_id=resolve_pack_id(req.description or req.issue_type or "electronics"),
                            )
                            return result
                except Exception as _tier2_exc:
                    import logging as _lg
                    _lg.getLogger("cv.analyze").warning("tier2 scan failed: %s", _tier2_exc, exc_info=True)
                return {}

            async def _run_consistency_task():
                try:
                    from src.app.routers.support_complaints import _evaluate_uploaded_images_consistency
                    return await _evaluate_uploaded_images_consistency(
                        sanitized_images=sanitized_images,
                        description=req.description,
                        issue_type=req.issue_type,
                        order_id=req.order_id,
                    )
                except Exception as _exc:
                    _log.warning("image consistency eval failed: %s", _exc, exc_info=True)
                    return None

            async def _run_qr_task():
                _qr_hits = []
                _qr_reasons = []
                _qr_injection = False
                _diag_count = 0
                try:
                    from src.app.rules.barcode_decode import decode_barcodes
                    from src.app.routers.support_complaints import _detect_ocr_prompt_injection

                    qr = await _asyncio.to_thread(
                        decode_barcodes,
                        [
                            (str(s.get("filename") or f"img_{i + 1}.jpg"), s.get("bytes") or b"")
                            for i, s in enumerate(sanitized_images or [])
                            if str(s.get("status") or "") == "sanitized"
                        ],
                    )
                    _qr_hits = qr.codes or []
                    _qr_reasons = getattr(qr, "reasons", []) or []
                    for c in _qr_hits:
                        _qr_payload = str(c.get("data") or "")
                        if _is_diagnostic_qr_payload(
                            _qr_payload,
                            context_text=" ".join([
                                str(req.description or ""),
                                str(req.issue_type or ""),
                                str(extracted_text or ""),
                            ]),
                        ):
                            _diag_count += 1
                            continue
                        if _detect_ocr_prompt_injection(_qr_payload):
                            _qr_injection = True
                            break
                except Exception as _exc:
                    _log.warning("QR/barcode decode failed: %s", _exc, exc_info=True)
                return _qr_hits, _qr_reasons, _qr_injection, _diag_count

            # Run all three in parallel
            _tier2_task = _run_tier2_task()
            _consistency_task = _run_consistency_task()
            _qr_task = _run_qr_task()
            tier2_result, image_consistency, (_qr_hits, _qr_reasons, _qr_inj, _diag_cnt) = await _asyncio.gather(
                _tier2_task, _consistency_task, _qr_task,
            )
            tier2_evidence_tags = list((tier2_result or {}).get("evidence_tags") or [])
            tier2_security = ((tier2_result or {}).get("security_analysis") or {}) if isinstance((tier2_result or {}).get("security_analysis"), dict) else {}
            qr_decode_hits = _qr_hits
            qr_decode_reasons = _qr_reasons
            qr_prompt_injection = _qr_inj
            diagnostic_qr_count = _diag_cnt

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
                            if _is_diagnostic_qr_payload(
                                data,
                                context_text=" ".join(
                                    [
                                        str(req.description or ""),
                                        str(req.issue_type or ""),
                                        str(extracted_text or ""),
                                    ]
                                ),
                            ):
                                continue
                            if data.lower().startswith(("http://", "https://")):
                                host = (urlparse(data).hostname or "").lower()
                                if host and host not in allow_hosts:
                                    qr_external_url = True
                                    break
                    except Exception:
                        qr_external_url = False

                suspicious_qr = bool(
                    (len(qr_decode_hits or []) - int(diagnostic_qr_count or 0)) > 0
                    and (qr_external_url or qr_prompt_injection)
                )
                if isinstance(image_consistency, dict) and isinstance(image_consistency.get("images"), list) and suspicious_qr:
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
            except Exception as _exc:
                _log.debug("QR tag folding into image_consistency skipped: %s", _exc)
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
                "qr_url_present": bool("qr_url_present" in tier2_evidence_tags),
                "qr_url_suspicious": bool("qr_url_suspicious" in tier2_evidence_tags),
                "manipulation_detected": bool("manipulation_detected" in tier2_evidence_tags),
                "prompt_injection_text_suspected": bool("prompt_injection_text_suspected" in tier2_evidence_tags),
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
        except Exception as _exc:
            _log.warning("security observer scan failed: %s", _exc, exc_info=True)
            security_details = {"severity": "info", "signals": {}}
            security_sev = "info"

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
        except Exception as _exc:
            _log.warning("evidence bundle enrichment failed: %s", _exc)
        evidence_id = persist_evidence_bundle(case_id, bundle)
        if not evidence_id:
            evidence_id = f"ev-{uuid.uuid4().hex}"

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
            suspicious_qr_detected = bool((len(qr_decode_hits or []) - int(diagnostic_qr_count or 0)) > 0)
            if qr_prompt_injection:
                sec_signals["qr_prompt_injection"] = True
            if suspicious_qr_detected:
                sec_signals["qr_code_detected"] = True
            if "qr_url_present" in tier2_evidence_tags:
                sec_signals["qr_url_present"] = True
            if "qr_url_suspicious" in tier2_evidence_tags:
                sec_signals["qr_url_suspicious"] = True
            if "manipulation_detected" in tier2_evidence_tags:
                sec_signals["manipulation_detected"] = True
            if "prompt_injection_text_suspected" in tier2_evidence_tags:
                sec_signals["prompt_injection_text_suspected"] = True
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
                "entities": {
                    "labels": (labels or [])[:20],
                    "qr_code_count": max(0, len(qr_decode_hits or []) - int(diagnostic_qr_count or 0)),
                    "diagnostic_qr_count": int(diagnostic_qr_count or 0),
                },
            }
            if tier2_evidence_tags:
                payload["evidence_tags"] = tier2_evidence_tags[:24]
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

        # Emit individual agent trace events so the Decision Trace Events tab shows each participant.
        try:
            if tier2_result:
                log_trace_event(
                    trace_id=case_id,
                    event_type="cv_pipeline",
                    source_type="agent",
                    source_id="CV_Tier2_Agent",
                    target_type="complaint",
                    target_id=case_id,
                    payload={
                        "tier": 2,
                        "evidence_tags": tier2_evidence_tags[:12],
                        "labels": (labels or [])[:12],
                        "ocr_length": len(extracted_text or ""),
                        "qr_count": len(qr_decode_hits or []),
                        "diagnostic_qr_count": int(diagnostic_qr_count or 0),
                        "tier2_summary": {
                            k: v for k, v in (tier2_result or {}).items()
                            if k in ("ocr_text_sample", "manipulation_score", "evidence_tags", "adversarial_score")
                        },
                    },
                )
        except Exception:
            pass
        try:
            if isinstance(image_consistency, dict):
                log_trace_event(
                    trace_id=case_id,
                    event_type="image_consistency_check",
                    source_type="agent",
                    source_id="Image_Consistency_Agent",
                    target_type="complaint",
                    target_id=case_id,
                    payload={
                        "status": image_consistency.get("status"),
                        "mismatch_count": image_consistency.get("mismatch_count", 0),
                        "suspicious_count": image_consistency.get("suspicious_count", 0),
                        "image_count": len(image_consistency.get("images") or []),
                    },
                )
        except Exception:
            pass
        try:
            # Use-case advisor context (labels → product intent)
            _detected_labels = [str(l) for l in (labels or [])[:8]]
            _ocr_sample = (extracted_text or "")[:200]
            _product_intent = "unknown"
            for _lbl in _detected_labels:
                _ll = _lbl.lower()
                if any(k in _ll for k in ("macbook", "apple", "mac")):
                    _product_intent = "macbook"
                    break
                if any(k in _ll for k in ("laptop", "notebook", "computer")):
                    _product_intent = "laptop"
                    break
                if any(k in _ll for k in ("phone", "iphone", "samsung")):
                    _product_intent = "phone"
                    break
            log_trace_event(
                trace_id=case_id,
                event_type="use_case_analysis",
                source_type="agent",
                source_id="Use_Case_Advisor_Agent",
                target_type="system",
                target_id=None,
                payload={
                    "detected_labels": _detected_labels,
                    "ocr_sample": _ocr_sample[:100],
                    "product_intent": _product_intent,
                    "description": (req.description or "")[:200],
                },
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
                retrieved_context = {
                    "cv_analysis": analysis,
                    "evidence_id": evidence_id,
                    "security_analysis": security_details if isinstance(security_details, dict) and security_details else {"severity": "info", "signals": {}},
                    "agent_chain": [
                        {"agent": "CV_Tier2_Agent", "status": "completed" if tier2_result else "skipped"},
                        {"agent": "Security_Observer_Agent", "status": "completed" if security_details else "skipped"},
                        {"agent": "Image_Consistency_Agent", "status": "completed" if image_consistency else "skipped"},
                    ],
                }
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
            except Exception as _exc:
                _log.warning("decision log failed: %s", _exc)
        except Exception as _exc:
            _log.warning("approval check block failed: %s", _exc)

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
            or bool("qr_url_present" in tier2_evidence_tags)
            or bool("qr_url_suspicious" in tier2_evidence_tags)
            or bool("manipulation_detected" in tier2_evidence_tags)
            or bool("prompt_injection_text_suspected" in tier2_evidence_tags)
            or (isinstance(image_consistency, dict) and image_consistency.get("status") in ("mismatch", "suspicious"))
        )

        # Progressive escalation tracking
        _escalation_level = "green"
        try:
            _client_key = ""
            if request and hasattr(request, "client") and request.client:
                _client_key = str(request.client.host)
            if not _client_key:
                _client_key = str(case_id)[:12]
            _has_suspicious_signal = bool(
                qr_prompt_injection or qr_external_url_detected
                or "manipulation_detected" in tier2_evidence_tags
                or "prompt_injection_text_suspected" in tier2_evidence_tags
                or (isinstance(image_consistency, dict) and image_consistency.get("status") in ("mismatch", "suspicious"))
            )
            if _has_suspicious_signal:
                _escalation_level = _record_suspicious_upload(_client_key)
            else:
                _escalation_level = _get_escalation_level(_client_key)
            # If red, emit escalation trace event
            if _escalation_level == "red":
                try:
                    log_trace_event(
                        trace_id=case_id,
                        event_type="security_escalation",
                        source_type="agent",
                        source_id="Progressive_Escalation_Agent",
                        target_type="session",
                        target_id=_client_key,
                        payload={
                            "escalation_level": _escalation_level,
                            "reason": "repeated_suspicious_uploads",
                            "action": "human_analyst_notified",
                        },
                    )
                except Exception:
                    pass
        except Exception:
            _escalation_level = "green"

        # Override needs_chat if escalation is orange or red
        if _escalation_level in ("orange", "red"):
            _needs_chat = True

        return {
            "status": "ok",
            "case_id": case_id,
            "cv_analysis": analysis,
            "cv_tiered_analysis": {"tier2": tier2_result} if tier2_result else None,
            "evidence_tags": tier2_evidence_tags[:24],
            "evidence_id": evidence_id,
            "trace_id": case_id,
            "image_consistency": image_consistency,
            "qr_codes": qr_decode_hits[:10],
            "qr_prompt_injection": qr_prompt_injection,
            "qr_classification": {
                "diagnostic_qr_count": int(diagnostic_qr_count or 0),
                "suspicious_qr_count": max(0, len(qr_decode_hits or []) - int(diagnostic_qr_count or 0)),
            },
            "security_matrix": {
                "details": security_details if isinstance(security_details, dict) and security_details else {"severity": "info", "signals": {}},
                "severity": security_sev or "info",
                "signals": {k: v for k, v in (security_details.get("signals") or {}).items() if isinstance(v, bool)} if isinstance(security_details, dict) else {},
            },
            "cv_runtime": runtime,
            "ui_actions": {"chat_with_admin": _needs_chat},
            "suggested_routing": "security_review" if _needs_chat else "standard_queue",
            "escalation_level": _escalation_level,
            "image_recommend_context": {
                "labels": (labels or [])[:12],
                "ocr_text": (extracted_text or "")[:500],
                "cv_signals": {
                    "qr_code_detected": bool(qr_decode_hits),
                    "qr_prompt_injection": bool(qr_prompt_injection),
                    "manipulation_detected": bool("manipulation_detected" in tier2_evidence_tags),
                },
            },
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
        gate = strict_image_ingest_gate(
            filename=str(normalized_filename or image.filename or "upload"),
            content_type=normalized_content_type or image.content_type,
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
                if not evidence_id:
                    evidence_id = f"ev-{uuid.uuid4().hex}"
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

        review_actions = {"human_review", "manual_approval", "policy_escalation"}
        human_review_required = any(str(a or "") in review_actions for a in (actions or []))
        security_analysis = (t2.get("security_analysis") or {}) if isinstance(t2, dict) else {}
        evidence_tags = list((t2.get("evidence_tags") or [])) if isinstance(t2, dict) else []
        severity = str((security_analysis.get("severity") or "")).lower()
        suggested_routing = "security_review" if human_review_required or severity in ("high", "critical", "error") else "standard_queue"

        return {
            "status": "ok",
            "case_id": case_id,
            "trace_id": trace_id,
            "decision_trace_id": trace_id,
            "cv_tier2": t2,
            "security_analysis": security_analysis,
            "evidence_tags": evidence_tags,
            "suggested_routing": suggested_routing,
            "human_review": {"status": "pending", "ticket_id": None} if human_review_required else False,
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
