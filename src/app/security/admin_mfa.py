from __future__ import annotations

import os
from fastapi import Request
from fastapi.responses import ORJSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from src.app.security.auth import get_role_from_key, ROLE_OWNER, ROLE_DEVELOPER


class AdminMfaMiddleware(BaseHTTPMiddleware):
    def __init__(self, app):
        super().__init__(app)
        try:
            self.enabled = str(os.getenv("ADMIN_MFA_ENABLED", "0")).lower() in ("1", "true", "yes")
        except Exception:
            self.enabled = False

    # The MFA enrollment routes must be reachable to bootstrap a fresh admin (they still require a
    # valid admin API key); never gate them behind the very factor they set up.
    _EXEMPT_PREFIXES = ("/api/v1/admin/mfa/",)

    async def dispatch(self, request: Request, call_next):
        if not self.enabled:
            return await call_next(request)
        p = request.url.path or ""
        if p.startswith("/api/v1/admin") and not any(p.startswith(ex) for ex in self._EXEMPT_PREFIXES):
            key = request.headers.get("x-api-key")
            role = get_role_from_key(key)
            if role in (ROLE_OWNER, ROLE_DEVELOPER):
                otp = (request.headers.get("x-mfa-otp") or "").strip()
                # Real per-admin TOTP. If the admin hasn't enrolled yet, require enrollment (fail
                # closed) rather than silently allowing access.
                from src.app.security import totp
                from src.app.security.mfa_store import get_secret
                secret, confirmed = get_secret(str(role))
                if not (secret and confirmed):
                    return ORJSONResponse(
                        {"error": "mfa_enrollment_required",
                         "message": "Admin MFA not set up — enroll at POST /api/v1/admin/mfa/enroll"},
                        status_code=401,
                    )
                # Back-compat break-glass: a static ADMIN_MFA_OTP still works if explicitly configured.
                _static = os.getenv("ADMIN_MFA_OTP", "")
                if totp.verify(secret, otp) or (_static and otp == _static.strip()):
                    return await call_next(request)
                return ORJSONResponse(
                    {"error": "mfa_required", "message": "Valid admin MFA code required"},
                    status_code=401,
                )
        return await call_next(request)
