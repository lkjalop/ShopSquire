from __future__ import annotations

from typing import Dict
from fastapi import APIRouter, Depends, Query, HTTPException
from src.app.security.auth import require_role_or_oidc, ROLE_OWNER, ROLE_DEVELOPER
from src.app.services.email_sendgrid import SendGridClient

router = APIRouter(prefix="/api/v1/admin/email", tags=["admin-email"])


@router.post("/send-test")
def send_test(
    to_email: str = Query(...),
    subject: str = Query("ShopSquire Test"),
    content: str = Query("This is a test email from ShopSquire."),
    role: str = Depends(require_role_or_oidc([ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, any]:
    cli = SendGridClient()
    res = cli.send_email(to_email, subject, content)
    if not res.get("ok"):
        raise HTTPException(status_code=500, detail=res.get("error") or "send_failed")
    return {"sent": True}