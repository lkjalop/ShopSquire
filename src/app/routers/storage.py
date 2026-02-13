from __future__ import annotations

from typing import Dict, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from src.app.security.auth import require_role_or_oidc, ROLE_OWNER, ROLE_DEVELOPER
from src.app.services.storage_s3 import get_default_storage

router = APIRouter(prefix="/api/v1/storage", tags=["storage"])


@router.get("/presign")
def presign_put(
    key: str = Query(..., description="Object key (path/filename)"),
    expires_in: int = Query(900, ge=60, le=86400),
    content_type: Optional[str] = Query(None),
    role: str = Depends(require_role_or_oidc([ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, any]:
    s3 = get_default_storage()
    res = s3.presign_put_url(key, expires_in=expires_in, content_type=content_type)
    if not res.get("ok"):
        raise HTTPException(status_code=500, detail=res.get("error") or "presign_failed")
    return res