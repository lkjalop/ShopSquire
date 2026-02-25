from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Body, Depends, Request
from fastapi.responses import ORJSONResponse, RedirectResponse

from src.app.security.auth import ROLE_DEVELOPER, ROLE_MERCHANT, ROLE_OWNER, require_role
from src.app.services.safe_links import create_safe_link, recheck_safe_link


router = APIRouter(prefix="/api/v1/safe-links", tags=["safe-links"])


@router.post("/rewrite")
def rewrite_link(
    payload: Dict[str, Any] = Body(default={}),
    role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    _ = role
    url = str((payload or {}).get("url") or "").strip()
    tenant_id = (payload or {}).get("tenant_id")
    campaign_id = (payload or {}).get("campaign_id")
    ttl_seconds = int((payload or {}).get("ttl_seconds") or 7 * 24 * 3600)
    if not url:
        return {"ok": False, "detail": "url_required"}
    try:
        out = create_safe_link(
            tenant_id=str(tenant_id) if tenant_id is not None else None,
            original_url=url,
            campaign_id=str(campaign_id) if campaign_id is not None else None,
            ttl_seconds=ttl_seconds,
        )
    except ValueError as exc:
        return {"ok": False, "detail": str(exc)}
    return {"ok": True, **out}


@router.get("/r/{token}")
def click_recheck(token: str, request: Request):
    ip = request.client.host if request.client else None
    ua = request.headers.get("user-agent")
    out = recheck_safe_link(token=token, ip=ip, user_agent=ua)
    if out.get("status") in ("invalid", "not_found"):
        return ORJSONResponse({"ok": False, **out}, status_code=404)
    if out.get("verdict") == "block":
        return ORJSONResponse({"ok": False, **out}, status_code=423)
    url = str(out.get("url") or "")
    if not url:
        return ORJSONResponse({"ok": False, **out, "detail": "missing_target_url"}, status_code=404)
    return RedirectResponse(url=url, status_code=307)
