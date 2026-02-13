from __future__ import annotations

from fastapi import Request
from fastapi.responses import ORJSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
import os


class PciBoundaryMiddleware(BaseHTTPMiddleware):
    def __init__(self, app):
        super().__init__(app)
        try:
            # Allow tests and local dev to opt out by setting DISABLE_UI_ROUTES
            if str(os.getenv("DISABLE_UI_ROUTES", "0")).strip().lower() in ("1", "true", "yes"):
                self.enabled = False
            else:
                env = os.getenv("APP_ENV", "local").lower()
                if env not in ("production", "prod"):
                    # Default to off for non-production unless explicitly enabled
                    self.enabled = str(os.getenv("PCI_BOUNDARY_ENFORCED", "0")).lower() in ("1", "true", "yes")
                else:
                    self.enabled = str(os.getenv("PCI_BOUNDARY_ENFORCED", "1")).lower() in ("1", "true", "yes")
        except Exception:
            self.enabled = True

    async def dispatch(self, request: Request, call_next):
        if not self.enabled:
            return await call_next(request)
        p = request.url.path or ""
        if p.startswith("/api/v1/payments"):
            flag = (request.headers.get("x-pci-boundary") or "").strip().lower()
            if flag not in ("1", "true", "yes"):
                return ORJSONResponse({"error": "pci_scope_violation", "message": "Payment boundary header required"}, status_code=403)
        return await call_next(request)
