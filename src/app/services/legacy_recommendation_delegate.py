"""Isolated compatibility boundary for recommendation lanes still owned by legacy."""
from __future__ import annotations

from typing import Any, Dict

from fastapi import Response


def delegate_legacy_recommendation(
    *, request: Any, params: Dict[str, Any], redis: Any, db: Any, role: str,
) -> Dict[str, Any]:
    """Invoke legacy suggest until each delegated lane has an independent owner."""
    from src.app.routers.recommend import suggest

    return suggest(
        request=request,
        uid=str(params.get("uid") or ""),
        query=str(params.get("query") or ""),
        budget_max=params.get("budget_max"),
        budget_min=params.get("budget_min"),
        nqe_question_id=params.get("nqe_question_id"),
        nqe_option_id=params.get("nqe_option_id"),
        nqe_option_label=params.get("nqe_option_label"),
        nqe_option_value=params.get("nqe_option_value"),
        image_labels=params.get("image_labels"),
        image_ocr_text=params.get("image_ocr_text"),
        image_hash=params.get("image_hash"),
        image_intent=params.get("image_intent"),
        image_product_identity=params.get("image_product_identity"),
        image_cv_signals=params.get("image_cv_signals"),
        fast_path=None,
        turn_intent=params.get("turn_intent"),
        include_summary=None,
        external_research_consent=(
            str(params.get("external_research_consent") or "").lower() == "true"
        ),
        copywriting_enabled=None,
        copywriting_profile=None,
        response=Response(),
        redis=redis,
        role=role,
        db=db,
    )
