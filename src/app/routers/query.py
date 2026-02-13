from __future__ import annotations

from typing import Dict

from fastapi import APIRouter, Depends, HTTPException

from src.app.security.auth import require_role, ROLE_DEVELOPER, ROLE_MERCHANT, ROLE_OWNER
from src.app.services.conversational_query import ConversationalQueryService
from src.app.services.faq_bank import match_faq
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

    faq, score = match_faq(q)
    if faq and score >= 2:
        return {
            "status": "ok",
            "source": "faq",
            "question": faq.get("q"),
            "answer": faq.get("a"),
            "confidence": min(1.0, score / 5.0),
        }

    tenant_id = (payload or {}).get("tenant_id")
    svc = ConversationalQueryService(db=db)
    result = svc.query(q, tenant_id=tenant_id)
    result["source"] = result.get("source") or "query_layer"
    return result
