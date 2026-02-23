from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException

from src.app.schemas.recruiting import (
    BatchScoreRequest,
    BatchScoreResponse,
    FeedbackRecord,
    FeedbackSummary,
    ParseResumeRequest,
    ParseResumeResponse,
    RankingRequest,
    RankingResponse,
    TriageOutcome,
    TriageRequest,
)
from src.app.security.auth import ROLE_DEVELOPER, ROLE_MERCHANT, ROLE_OWNER, require_role
from src.app.services.decision_log import log_decision, log_trace_event
from src.app.services.recruiting_pipeline import (
    batch_score,
    feedback_summary,
    parse_resume,
    rank_candidates,
    record_feedback,
    triage_candidate,
)


router = APIRouter(prefix="/api/v1/recruiting", tags=["recruiting"])


def _bitemporal_now() -> Dict[str, str]:
    now = datetime.utcnow().isoformat()
    return {
        "valid_from": now,
        "valid_to": "infinity",
        "system_from": now,
        "system_to": "infinity",
    }


@router.post("/resume/parse", response_model=ParseResumeResponse)
def parse_resume_endpoint(
    req: ParseResumeRequest,
    role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER])),
) -> ParseResumeResponse:
    try:
        out = parse_resume(req)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"parse_failed: {exc}") from exc
    trace_id = str(req.candidate_id or f"resume-{uuid.uuid4().hex[:12]}")
    try:
        log_trace_event(
            trace_id=trace_id,
            event_type="candidate_retrieve",
            source_type="agent",
            source_id="Recruiting_Parse_Agent",
            target_type="candidate",
            target_id=req.candidate_id,
            payload={
                "pipeline": out.pipeline,
                "warnings": out.warnings,
                "resume_hash": out.resume.raw_text_hash,
                "citations_count": len(out.citations or []),
                "bitemporal": _bitemporal_now(),
            },
        )
    except Exception:
        pass
    return out


@router.post("/triage", response_model=TriageOutcome)
def triage_endpoint(
    req: TriageRequest,
    role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER])),
) -> TriageOutcome:
    try:
        out = triage_candidate(req)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"triage_failed: {exc}") from exc
    trace_id = str(out.trace_id or f"triage-{uuid.uuid4().hex[:12]}")
    out.trace_id = trace_id
    try:
        log_decision(
            agent_name="Recruiting_Triage_Agent",
            input_data={
                "candidate_id": out.candidate_id,
                "job_id": out.job_id,
                "mode": req.mode,
                "latency_path": req.latency_path,
            },
            retrieved_context={
                "proxy_attributes": req.proxy_attributes,
                "use_semantic_cache": req.use_semantic_cache,
            },
            proposed_action={
                "decision": out.decision,
                "route": out.route,
                "score": out.score,
                "reasons": out.reasons,
                "trace_id": trace_id,
            },
            agent_reasoning="Deterministic recruiting triage with explainable feature contributions.",
            event_type="candidate_rerank",
        )
    except Exception:
        pass
    try:
        log_trace_event(
            trace_id=trace_id,
            event_type="candidate_rerank",
            source_type="agent",
            source_id="Recruiting_Triage_Agent",
            target_type="candidate",
            target_id=out.candidate_id,
            payload={
                "job_id": out.job_id,
                "score": out.score,
                "decision": out.decision,
                "route": out.route,
                "mode": out.mode,
                "latency_path": out.latency_path,
                "feature_contributions": [c.model_dump() for c in (out.feature_contributions or [])],
                "citations": out.citations,
                "bitemporal": _bitemporal_now(),
            },
        )
    except Exception:
        pass
    return out


@router.post("/rank", response_model=RankingResponse)
def rank_endpoint(
    req: RankingRequest,
    role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER])),
) -> RankingResponse:
    try:
        out = rank_candidates(req)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"rank_failed: {exc}") from exc
    trace_id = str(req.job.job_id or f"rank-{uuid.uuid4().hex[:12]}")
    try:
        log_trace_event(
            trace_id=trace_id,
            event_type="candidate_rerank",
            source_type="agent",
            source_id="Recruiting_Ranking_Agent",
            target_type="job",
            target_id=req.job.job_id,
            payload={
                "job_id": out.job_id,
                "top_k": req.top_k,
                "ranked_count": len(out.ranked or []),
                "fairness": [f.model_dump() for f in (out.fairness or [])],
                "metadata": out.metadata,
                "bitemporal": _bitemporal_now(),
            },
        )
    except Exception:
        pass
    return out


@router.post("/score/batch", response_model=BatchScoreResponse)
def batch_score_endpoint(
    req: BatchScoreRequest,
    role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER])),
) -> BatchScoreResponse:
    try:
        out = batch_score(req)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"batch_score_failed: {exc}") from exc
    trace_id = str(out.batch_id or f"batch-{uuid.uuid4().hex[:10]}")
    try:
        log_trace_event(
            trace_id=trace_id,
            event_type="tool_budget",
            source_type="agent",
            source_id="Recruiting_Batch_Agent",
            target_type="job",
            target_id=req.job.job_id,
            payload={
                "batch_id": out.batch_id,
                "processed": out.processed,
                "shortlisted": out.shortlisted,
                "review": out.review,
                "rejected": out.rejected,
                "metadata": out.metadata,
                "bitemporal": _bitemporal_now(),
            },
        )
    except Exception:
        pass
    return out


@router.post("/feedback")
def feedback_endpoint(
    req: FeedbackRecord,
    role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    try:
        stored = record_feedback(req)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"feedback_failed: {exc}") from exc
    trace_id = str(req.trace_id or f"feedback-{uuid.uuid4().hex[:12]}")
    try:
        log_trace_event(
            trace_id=trace_id,
            event_type="feedback_loop",
            source_type="human",
            source_id="Recruiter",
            target_type="candidate",
            target_id=req.candidate_id,
            payload={
                "job_id": req.job_id,
                "recruiter_decision": req.recruiter_decision,
                "model_decision": req.model_decision,
                "model_score": req.model_score,
                "feedback_id": stored.get("id"),
                "bitemporal": _bitemporal_now(),
            },
        )
    except Exception:
        pass
    return stored


@router.get("/feedback/summary", response_model=FeedbackSummary)
def feedback_summary_endpoint(
    job_id: Optional[str] = None,
    role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER])),
) -> FeedbackSummary:
    try:
        return feedback_summary(job_id=job_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"feedback_summary_failed: {exc}") from exc
