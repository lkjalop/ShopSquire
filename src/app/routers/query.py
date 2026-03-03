from __future__ import annotations

from typing import Dict

from fastapi import APIRouter, Depends, HTTPException

from src.app.security.auth import require_role, ROLE_DEVELOPER, ROLE_MERCHANT, ROLE_OWNER
from src.app.services.conversational_query import ConversationalQueryService
from src.app.services.faq_bank import match_faq
from src.app.services.faq_v2 import semantic_match_faq
from src.app.services.agentic_rag_pipeline import run_agentic_rag_pipeline
from src.app.models.db import get_db


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
        out = run_agentic_rag_pipeline(
            question=q,
            trace_id=(payload or {}).get("trace_id"),
            context_budget_chars=int((payload or {}).get("context_budget_chars") or 1400),
            max_chunks=int((payload or {}).get("max_chunks") or 5),
        )
        out["source"] = "agentic_rag"
        return out

    persona = str((payload or {}).get("persona") or ("admin" if role in (ROLE_OWNER, ROLE_DEVELOPER) else "buyer")).lower()
    faq2, score2, intent = semantic_match_faq(q, role=persona)
    if faq2 and score2 >= 0.2:
        return {
            "status": "ok",
            "source": "faq_v2",
            "intent": intent,
            "question": faq2.get("q"),
            "answer": faq2.get("a"),
            "confidence": score2,
        }
    faq, score = match_faq(q)
    if faq and score >= 2:
        return {"status": "ok", "source": "faq", "question": faq.get("q"), "answer": faq.get("a"), "confidence": min(1.0, score / 5.0)}

    tenant_id = (payload or {}).get("tenant_id")
    svc = ConversationalQueryService(db=db)
    result = svc.query(q, tenant_id=tenant_id)
    result["source"] = result.get("source") or "query_layer"
    return result
