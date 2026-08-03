from __future__ import annotations

from typing import Dict

from fastapi import APIRouter, Depends, HTTPException

from src.app.security.auth import require_role, ROLE_DEVELOPER, ROLE_MERCHANT, ROLE_OWNER
from src.app.services.conversational_query import ConversationalQueryService
from src.app.services.faq_v2 import resolve_faq_match
from src.app.services.agentic_rag_pipeline import run_agentic_rag_pipeline
from src.app.services.temporal_invalidation import cache_lifecycle, register_cache_dependency
from src.app.services.response_normalizer import ResponseNormalizer
from src.app.models.db import get_db
from src.app.platform.tenant_context import current_tenant_id


router = APIRouter(prefix="/api/v1/query", tags=["query"])


@router.post("")
def query(
    payload: Dict,
    db=Depends(get_db),
    role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict:
    q = (payload or {}).get("query") or ""
    if not q.strip():
        raise HTTPException(status_code=400, detail="query_required")
    use_agentic_rag = bool((payload or {}).get("dynamic_injection") or str((payload or {}).get("pipeline") or "").lower() == "agentic_rag")
    if use_agentic_rag:
        def record_cache_dependency(item: dict) -> None:
            try:
                register_cache_dependency(db, **item)
                db.commit()
            except Exception:
                db.rollback()
                raise

        def resolve_cache_lifecycle(item: dict[str, str]) -> dict:
            return cache_lifecycle(db, **item)

        out = run_agentic_rag_pipeline(
            question=q,
            trace_id=(payload or {}).get("trace_id"),
            context_budget_chars=int((payload or {}).get("context_budget_chars") or 1400),
            max_chunks=int((payload or {}).get("max_chunks") or 5),
            tenant_id=current_tenant_id(),
            subject_id=str((payload or {}).get("case_id") or ""),
            session_epoch=str((payload or {}).get("session_epoch") or ""),
            cache_dependency_recorder=record_cache_dependency,
            cache_lifecycle_resolver=resolve_cache_lifecycle,
        )
        out["source"] = "agentic_rag"
        return out

    persona = str((payload or {}).get("persona") or ("admin" if role in (ROLE_OWNER, ROLE_DEVELOPER) else "buyer")).lower()
    faq = resolve_faq_match(q, role=persona)
    if faq:
        return {
            "status": "ok",
            "source": faq.get("source"),
            "intent": faq.get("intent"),
            "question": faq.get("question"),
            "answer": ResponseNormalizer.polish_llm_text(str(faq.get("answer") or ""), query=q),
            "confidence": faq.get("confidence"),
        }

    tenant_id = (payload or {}).get("tenant_id")
    svc = ConversationalQueryService(db=db)
    result = svc.query(q, tenant_id=tenant_id)
    result["source"] = result.get("source") or "query_layer"
    if isinstance(result.get("answer"), str):
        result["answer"] = ResponseNormalizer.polish_llm_text(result["answer"], query=q)
    return result
