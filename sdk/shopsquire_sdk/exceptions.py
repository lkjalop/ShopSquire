"""SDK exception types — one class per error category."""
from __future__ import annotations


class ShopSquireError(Exception):
    """Base exception for all ShopSquire SDK errors."""

    def __init__(self, message: str, status_code: int | None = None, code: str | None = None, detail: dict | None = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.code = code
        self.detail = detail or {}

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(message={self.message!r}, status_code={self.status_code}, code={self.code!r})"


class ValidationError(ShopSquireError):
    """422 — Request validation failed."""


class NotFoundError(ShopSquireError):
    """404 — Resource not found."""


class AuthenticationError(ShopSquireError):
    """401 — Authentication required or invalid credentials."""


class AuthorizationError(ShopSquireError):
    """403 — Insufficient permissions."""


class RateLimitError(ShopSquireError):
    """429 — Rate limit exceeded."""


class ConflictError(ShopSquireError):
    """409 — Conflict (e.g., duplicate resource)."""


class ServerError(ShopSquireError):
    """5xx — Server-side error."""


_STATUS_TO_EXCEPTION: dict[int, type[ShopSquireError]] = {
    400: ValidationError,
    401: AuthenticationError,
    403: AuthorizationError,
    404: NotFoundError,
    409: ConflictError,
    422: ValidationError,
    429: RateLimitError,
}


def raise_for_status(status_code: int, body: dict) -> None:
    """Raise the appropriate SDK exception for a given HTTP status code."""
    exc_class = _STATUS_TO_EXCEPTION.get(status_code)
    if exc_class is None and status_code >= 500:
        exc_class = ServerError
    if exc_class is None:
        return  # 2xx / 3xx — no error
    message = body.get("message") or body.get("detail") or f"HTTP {status_code}"
    if isinstance(message, dict):
        message = str(message)
    raise exc_class(
        message=message,
        status_code=status_code,
        code=body.get("code"),
        detail=body,
    )
