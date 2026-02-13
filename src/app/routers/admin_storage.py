from __future__ import annotations

from typing import Dict
from fastapi import APIRouter, Depends
from src.app.security.auth import require_role_or_oidc, ROLE_OWNER, ROLE_DEVELOPER
from src.app.services.storage_s3 import get_default_storage

router = APIRouter(prefix="/api/v1/admin/storage", tags=["admin-storage"])


@router.get("/minio/health")
def minio_health(role: str = Depends(require_role_or_oidc([ROLE_OWNER, ROLE_DEVELOPER]))) -> Dict[str, any]:
    s3 = get_default_storage()
    return s3.health()