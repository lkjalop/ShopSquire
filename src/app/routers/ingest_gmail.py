from __future__ import annotations

import base64
import hmac
import json
import os
from typing import Any, Dict, Optional

from fastapi import APIRouter, Header, HTTPException, Request

from src.app.observability.metrics import record_email_security_connector_event, record_email_security_connector_failure
from src.app.security.email_security import evaluate_email_security

router = APIRouter(prefix="/api/v1/ingest/gmail", tags=["ingest-gmail"])


def _apply_supplier_domain_guard(email: dict) -> dict:
    """Validate email sender domain against the trusted_supplier_domains allowlist.

    Mutates *email* in-place by adding:
      - supplier_domain_trusted: bool
      - supplier_domain_quarantine_id: str | None

    Non-fatal: if the guard raises, the email proceeds with trusted=False so the
    security evaluation can still inspect it and flag it accordingly.
    """
    try:
        from src.app.services.supplier_domain_guard import validate_supplier_email
        _guard = validate_supplier_email(
            str(email.get("from_addr") or ""),
            operation="email_ingest_gmail",
            payload_summary=str(email.get("subject") or "")[:120],
        )
        email["supplier_domain_trusted"] = _guard.get("trusted", False)
        email["supplier_domain_quarantine_id"] = _guard.get("quarantine_id")
    except Exception:
        email["supplier_domain_trusted"] = False
        email["supplier_domain_quarantine_id"] = None
    return email


def _check_secret(secret: str | None) -> None:
    expected = os.getenv("GMAIL_INGEST_SECRET") or os.getenv("EMAIL_INGEST_SECRET") or ""
    if not expected:
        # If not configured, fail closed (production safety).
        raise HTTPException(status_code=503, detail="ingest_secret_not_configured")
    if not secret or not hmac.compare_digest(str(secret), str(expected)):
        raise HTTPException(status_code=401, detail="invalid_secret")


@router.post("/pubsub")
async def pubsub_push(
    request: Request,
    x_ingest_secret: Optional[str] = Header(default=None, alias="X-Ingest-Secret"),
):
    """Receive Gmail push notifications (typically via Google Pub/Sub push).

    Production note: this endpoint validates a shared secret header. A full JWT
    verification of Pub/Sub push identity can be added later.
    """
    _check_secret(x_ingest_secret)
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    tenant_id = None
    try:
        tenant_id = (payload.get("tenant_id") or request.headers.get("X-Tenant-Id") or request.headers.get("x-tenant-id"))
    except Exception:
        tenant_id = None

    record_email_security_connector_event(tenant_id, "gmail")

    # Allow a direct canonical email payload for MVP/demo connector workers:
    email = payload.get("email") if isinstance(payload, dict) else None
    if isinstance(email, dict) and email.get("from_addr"):
        email = dict(email)
        email["provider"] = "gmail"
        _apply_supplier_domain_guard(email)
        evaluate_email_security(email, tenant_id=tenant_id)
        return {"ok": True}

    # Pub/Sub push format: {message: {data: base64(...)}, subscription: "..."}
    try:
        msg = (payload.get("message") or {}) if isinstance(payload, dict) else {}
        data_b64 = msg.get("data")
        if data_b64:
            raw = base64.b64decode(data_b64).decode("utf-8", errors="ignore")
            # Some connector workers put canonical payload inside the data field.
            try:
                inner = json.loads(raw)
            except Exception:
                inner = {"raw": raw}
            email2 = inner.get("email") if isinstance(inner, dict) else None
            if isinstance(email2, dict) and email2.get("from_addr"):
                email2 = dict(email2)
                email2["provider"] = "gmail"
                # Apply supplier domain guard to pub/sub decoded path too
                _apply_supplier_domain_guard(email2)
                evaluate_email_security(email2, tenant_id=tenant_id)
                return {"ok": True}
            # Notification-only mode (real Gmail watch): enqueue for worker fetch.
            # Expected fields: { "emailAddress": "...", "historyId": "..." }
            try:
                if isinstance(inner, dict) and inner.get("emailAddress") and inner.get("historyId"):
                    from src.app.deps import get_redis

                    r = get_redis()
                    if r.__class__.__name__ == "DummyRedis":
                        # Without Redis we can't queue notifications reliably.
                        raise HTTPException(status_code=503, detail="redis_required_for_notification_mode")
                    r.lpush(
                        "q:email:gmail",
                        json.dumps(
                            {
                                "tenant_id": tenant_id,
                                "emailAddress": str(inner.get("emailAddress")),
                                "historyId": str(inner.get("historyId")),
                            }
                        ),
                    )
                    return {"ok": True, "queued": True}
            except HTTPException:
                raise
            except Exception:
                pass
    except Exception as exc:
        record_email_security_connector_failure(tenant_id, "gmail", "decode_error")
        raise HTTPException(status_code=400, detail=f"bad_payload:{exc}")

    # No-op for notification-only mode (fetching from Gmail API is handled in connector workers).
    return {"ok": True}
