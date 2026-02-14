from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from typing import Any, Dict, List, Optional
import time

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


router = APIRouter(prefix="/api/v1/cv", tags=["cv"])


class CVAnalyzeRequest(BaseModel):
    case_id: Optional[str] = None
    labels: List[str] = []
    extracted_text: Optional[str] = None
    provider: str = "basic"
    model: str = "cv_triage_basic"
    images: Optional[List[Dict[str, Any]]] = None  # sanitized image metadata (mime, size, sha256, phash)
    description: Optional[str] = None
    issue_type: Optional[str] = None


@router.post("/analyze")
async def analyze(req: CVAnalyzeRequest, role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER]))) -> Dict[str, Any]:
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
        # Prefer Tiered CV provider which chooses analysis tier based on signals
        try:
            triager = TieredCVProvider(flags={})
        except Exception:
            triager = BasicCVTriage()
        started = time.time()
        analysis = call_with_resilience(
            "cv.analyze",
            lambda: __import__("asyncio").run(
                triager.analyze(
                    req.labels or [],
                    req.extracted_text or "",
                    context={"query": req.description or "", "risk_adj": 0.0},
                )
            ),
            timeout_s=6.0,
            retries=1,
        )
        processing_ms = int((time.time() - started) * 1000)

        case_id = req.case_id or __import__("uuid").uuid4().hex
        try:
            persist_cv_analysis(
                case_id=case_id,
                image_sha256=None,
                image_phash=None,
                analysis=analysis,
                labels=req.labels or [],
                extracted_text=req.extracted_text or "",
                provider=req.provider,
                model=req.model,
                processing_time_ms=processing_ms,
            )
        except Exception:
            pass

        # Build and persist evidence bundle
        bundle = build_evidence_bundle(
            case_id=case_id,
            sanitized_images=req.images or [],
            labels=req.labels or [],
            extracted_text=req.extracted_text or "",
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
                payload={"analysis": analysis, "evidence_id": evidence_id, "processing_ms": processing_ms},
            )
        except Exception:
            pass

        # Persist a minimal decision_logs entry when CV forensics indicates high severity
        try:
            verdict = (analysis or {}).get("verdict") or {}
            required_actions = verdict.get("required_actions") or []
            sev = (verdict.get("severity") or "").lower()
            critical_actions = {"human_review", "manual_approval", "policy_escalation", "nonce_live_capture"}
            if sev in ("high", "critical") or any(a in critical_actions for a in required_actions):
                try:
                    input_payload = {"case_id": case_id, "extract_sample": (req.extracted_text or "")[:1024]}
                    retrieved_context = {"cv_analysis": analysis, "evidence_id": evidence_id}
                    proposed_action = {"required_actions": required_actions, "verdict": verdict}
                    log_decision(
                        agent_name="cv_forensics",
                        input_data=input_payload,
                        retrieved_context=retrieved_context,
                        proposed_action=proposed_action,
                        policy_version="v1",
                        approval_required=True,
                        execution_status="review_required",
                        decision_id=case_id,
                    )
                except Exception:
                    pass
        except Exception:
            pass

        return {
            "status": "ok",
            "case_id": case_id,
            "cv_analysis": analysis,
            "evidence_id": evidence_id,
        }
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
    sku: str | None = Query(default=None),
    expected_label: str | None = Query(default=None),
    issue_type: str | None = Query(default=None),
    description: str | None = Query(default=None),
    role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    """Upload an image, run Tier 2 CV including forensics verdict, and return a decision hint.

    If `nonce` is provided, it is checked for recent issuance (best-effort).
    """
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
        # Always allocate a unique case id for this upload so evidence/decisions don't collide on filename.
        case_id = uuid.uuid4().hex

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
                res = storage.upload_bytes(key, data_bytes, content_type=(image.content_type or None))
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
                        "filename": image.filename,
                        "content_type": image.content_type,
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
        t2 = call_with_resilience(
            "cv.tier2",
            lambda: run_tier2(
                content,
                meta={
                    "case_id": case_id,
                    "filename": image.filename,
                    "content_type": image.content_type,
                    "order_id": order_id,
                    "order_ctx": order_ctx,
                    "sku": sku,
                    "expected_label": expected_label,
                    "issue_type": issue_type,
                    "description": description,
                },
                pack_id=pack_id,
            ),
            timeout_s=8.0,
            retries=1,
        )
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
    except Exception:
        # Avoid leaking internal exception details in HTTP response
        raise HTTPException(status_code=400, detail="upload failed: processing error")
