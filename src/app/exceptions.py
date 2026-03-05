"""ShopSquire structured exception hierarchy.

Every domain error inherits from ``ShopSquireError`` so that the global
exception handler in ``main.py`` can:
  1. Return a consistent JSON envelope  ``{"error": "<code>", "message": "…"}``
  2. Set the correct HTTP status code
  3. Emit typed error metrics (``shopsquire_errors_total{code=…}``)

Usage in routers::

    from src.app.exceptions import NotFoundError, ValidationError

    raise NotFoundError("Product not found", detail={"sku": sku})
"""
from __future__ import annotations

from typing import Any, Dict, Optional


class ShopSquireError(Exception):
    """Base for all ShopSquire application errors.

    Attributes:
        status_code: HTTP status to return (default 500).
        code:        Machine-readable error code (e.g. ``"not_found"``).
        message:     Human-readable description.
        detail:      Optional structured payload for debugging.
    """

    status_code: int = 500
    code: str = "internal_error"

    def __init__(
        self,
        message: str = "An unexpected error occurred",
        *,
        detail: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail or {}

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"error": self.code, "message": self.message}
        if self.detail:
            payload["detail"] = self.detail
        return payload


# ── 4xx client errors ──

class ValidationError(ShopSquireError):
    status_code = 422
    code = "validation_error"

    def __init__(self, message: str = "Validation failed", **kwargs: Any) -> None:
        super().__init__(message, **kwargs)


class NotFoundError(ShopSquireError):
    status_code = 404
    code = "not_found"

    def __init__(self, message: str = "Resource not found", **kwargs: Any) -> None:
        super().__init__(message, **kwargs)


class AuthenticationError(ShopSquireError):
    status_code = 401
    code = "authentication_error"

    def __init__(self, message: str = "Authentication required", **kwargs: Any) -> None:
        super().__init__(message, **kwargs)


class AuthorizationError(ShopSquireError):
    status_code = 403
    code = "authorization_error"

    def __init__(self, message: str = "Insufficient permissions", **kwargs: Any) -> None:
        super().__init__(message, **kwargs)


class RateLimitError(ShopSquireError):
    status_code = 429
    code = "rate_limit_exceeded"

    def __init__(self, message: str = "Rate limit exceeded", **kwargs: Any) -> None:
        super().__init__(message, **kwargs)


class ConflictError(ShopSquireError):
    status_code = 409
    code = "conflict"

    def __init__(self, message: str = "Resource conflict", **kwargs: Any) -> None:
        super().__init__(message, **kwargs)


# ── 5xx server errors ──

class ServiceUnavailableError(ShopSquireError):
    status_code = 503
    code = "service_unavailable"

    def __init__(self, message: str = "Service temporarily unavailable", **kwargs: Any) -> None:
        super().__init__(message, **kwargs)


class ExternalServiceError(ShopSquireError):
    status_code = 502
    code = "external_service_error"

    def __init__(self, message: str = "External service call failed", **kwargs: Any) -> None:
        super().__init__(message, **kwargs)
