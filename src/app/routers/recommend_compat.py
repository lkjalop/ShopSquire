"""Deprecated /recommend/suggest transport backed exclusively by recommendation V2."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Request, Response

from src.app.deps import get_redis
from src.app.models.db import get_db
from src.app.security.auth import (
    ROLE_DEVELOPER,
    ROLE_MERCHANT,
    ROLE_OWNER,
    require_role,
)
from src.app.services.recommendation_compatibility import serve_v2_compatibility

router = APIRouter(prefix="/api/v1/recommend", tags=["recommend-compat"])


@router.get("/suggest", deprecated=True)
def suggest(
    request: Request,
    uid: str,
    query: str,
    budget_max: Optional[float] = None,
    budget_min: Optional[float] = None,
    nqe_question_id: Optional[str] = None,
    nqe_option_id: Optional[str] = None,
    nqe_option_label: Optional[str] = None,
    nqe_option_value: Optional[str] = None,
    image_labels: Optional[str] = None,
    image_ocr_text: Optional[str] = None,
    image_hash: Optional[str] = None,
    image_intent: Optional[str] = None,
    image_product_identity: Optional[str] = None,
    image_cv_signals: Optional[str] = None,
    fast_path: Optional[bool] = None,
    turn_intent: Optional[str] = None,
    include_summary: Optional[bool] = None,
    external_research_consent: Optional[bool] = None,
    copywriting_enabled: Optional[bool] = None,
    copywriting_profile: Optional[str] = None,
    response: Response = None,
    redis=Depends(get_redis),
    role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER])),
    db=Depends(get_db),
) -> Dict[str, Any]:
    if response is not None:
        response.headers["Deprecation"] = "true"
        response.headers["Sunset"] = "Wed, 30 Sep 2026 00:00:00 GMT"
        response.headers["Warning"] = '299 ShopSquire "/recommend/suggest is deprecated; use chat V2"'
        response.headers["Link"] = '</api/v1/chat/query>; rel="successor-version"'
        response.headers["X-Recommendation-Engine"] = "v2-compatibility"
    return serve_v2_compatibility(
        request=request,
        params={
            "uid": uid,
            "query": query,
            "budget_max": budget_max,
            "budget_min": budget_min,
            "nqe_question_id": nqe_question_id,
            "nqe_option_id": nqe_option_id,
            "nqe_option_label": nqe_option_label,
            "nqe_option_value": nqe_option_value,
            "image_labels": image_labels,
            "image_ocr_text": image_ocr_text,
            "image_hash": image_hash,
            "image_intent": image_intent,
            "image_product_identity": image_product_identity,
            "image_cv_signals": image_cv_signals,
            "fast_path": fast_path,
            "turn_intent": turn_intent,
            "include_summary": include_summary,
            "external_research_consent": bool(external_research_consent),
            "copywriting_enabled": copywriting_enabled,
            "copywriting_profile": copywriting_profile,
            "compatibility_requested_at": datetime.now(timezone.utc).isoformat(),
        },
        redis=redis,
        db=db,
        role=role,
    )
