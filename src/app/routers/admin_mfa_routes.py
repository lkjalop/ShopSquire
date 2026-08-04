"""Admin MFA enrollment endpoints (PCI #5) — real per-admin TOTP.

Flow: an authenticated admin (owner/developer key) calls /enroll to get a fresh TOTP secret + an
otpauth:// provisioning URI (scan into any authenticator app), then /confirm with a current code to
activate MFA for that principal. Thereafter AdminMfaMiddleware requires a valid TOTP on /api/v1/admin.

These three routes are intentionally exempt from the MFA gate (see AdminMfaMiddleware) so a fresh
admin can bootstrap — they still require a valid owner/developer API key.
"""
from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel
from typing import Optional

from src.app.security import totp
from src.app.security.auth import get_role_from_key, ROLE_OWNER, ROLE_DEVELOPER
from src.app.security.mfa_store import set_secret, get_secret, confirm, is_enrolled

router = APIRouter(prefix="/api/v1/admin/mfa", tags=["admin-mfa"])

_PRIVILEGED = {ROLE_OWNER, ROLE_DEVELOPER}


def _principal(x_api_key: Optional[str]) -> str:
    role = get_role_from_key(x_api_key)
    if role not in _PRIVILEGED:
        raise HTTPException(status_code=401, detail="admin key required")
    return str(role)


class ConfirmBody(BaseModel):
    code: str


@router.get("/status")
def mfa_status(x_api_key: Optional[str] = Header(default=None)):
    principal = _principal(x_api_key)
    _secret, confirmed = get_secret(principal)
    return {"principal": principal, "enrolled": bool(_secret), "confirmed": bool(confirmed)}


@router.post("/enroll")
def mfa_enroll(x_api_key: Optional[str] = Header(default=None)):
    principal = _principal(x_api_key)
    secret = totp.generate_secret()
    set_secret(principal, secret)
    return {
        "principal": principal,
        "secret": secret,
        "otpauth_uri": totp.provisioning_uri(secret, account_name=principal, issuer="ShopSquire"),
        "next": "POST /api/v1/admin/mfa/confirm with a current 6-digit code to activate",
    }


@router.post("/confirm")
def mfa_confirm(body: ConfirmBody, x_api_key: Optional[str] = Header(default=None)):
    principal = _principal(x_api_key)
    secret, _confirmed = get_secret(principal)
    if not secret:
        raise HTTPException(status_code=400, detail="not enrolled — call /enroll first")
    if not totp.verify(secret, body.code):
        raise HTTPException(status_code=401, detail="invalid code")
    confirm(principal)
    return {"principal": principal, "confirmed": True}
