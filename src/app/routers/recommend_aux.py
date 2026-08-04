from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException

from src.app.deps import get_redis
from src.app.security.auth import ROLE_DEVELOPER, ROLE_OWNER, require_role
from src.app.services.recommendation_als import train_recommend_als
from src.app.services.recommend_narration_jobs import get_narration


router = APIRouter(prefix="/api/v1/recommend", tags=["recommend"])


@router.get("/narration/{job_id}")
def get_narration_job(job_id: str, redis=Depends(get_redis)) -> Dict[str, Any]:
    """Poll an async narration job without depending on the legacy suggest router."""
    out = get_narration(redis, job_id)
    if not isinstance(out, dict):
        return {"status": "pending", "assistant_message": None}
    return out


@router.post("/cf/train")
def train_recommend_cf(
    lookback_days: int = 120,
    topk_per_user: int = 80,
    factors: int = 12,
    iters: int = 6,
    role: str = Depends(require_role([ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    try:
        out = train_recommend_als(
            lookback_days=max(30, min(int(lookback_days or 120), 365)),
            topk_per_user=max(20, min(int(topk_per_user or 80), 200)),
            factors=max(6, min(int(factors or 12), 64)),
            iters=max(2, min(int(iters or 6), 25)),
        )
        return {"status": "ok", "job": out}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"cf_train_failed: {exc}") from exc
