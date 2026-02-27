import os

from fastapi import APIRouter, Header, HTTPException, Depends
from fastapi.responses import RedirectResponse
from src.app.security.auth import require_role, ROLE_OWNER, ROLE_DEVELOPER

router = APIRouter()


@router.get("/api/v1/admin/interleaving/ui")
def interleaving_ui(
    role: str = Depends(require_role([ROLE_OWNER, ROLE_DEVELOPER])),
    tenant_id: str | None = Header(default=None, alias="X-Tenant-Id"),
):
    """Protected redirect to the static admin interleaving UI."""
    env = os.getenv("APP_ENV", "local").strip().lower()
    # Enforce tenant assertion for admin UI in non-local environments.
    if env not in ("local", "dev", "development", "test") and not str(tenant_id or "").strip():
        raise HTTPException(status_code=400, detail="missing_tenant_scope")
    return RedirectResponse(url="/static/admin_interleaving.html")
