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

    async def dispatch(self, request: Request, call_next):
        if not self.enabled:
            return await call_next(request)
        p = request.url.path or ""
        if p.startswith("/api/v1/admin"):
            key = request.headers.get("x-api-key")
            role = get_role_from_key(key)
            if role in (ROLE_OWNER, ROLE_DEVELOPER):
                otp = request.headers.get("x-mfa-otp") or ""
                expect = os.getenv("ADMIN_MFA_OTP", "")
                if not expect or otp.strip() != expect.strip():
                    return ORJSONResponse({"error": "mfa_required", "message": "Admin MFA required"}, status_code=401)
        return await call_next(request)
