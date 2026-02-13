from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/api/v1/intent", tags=["intent"])


class InferBody(BaseModel):
    text: str


@router.post("/infer")
def infer(body: InferBody):
    try:
        from src.app.analytics.xgb_intent import infer_intent
        res = infer_intent(body.text or "")
        return res
    except Exception:
        return {"intent": "browse", "proba": {"browse": 0.5}}