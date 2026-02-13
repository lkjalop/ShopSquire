from __future__ import annotations

import hmac
import os
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Request, Depends
from fastapi.responses import PlainTextResponse

from src.app.observability.metrics import record_email_security_connector_event, record_email_security_connector_failure
from src.app.security.email_security import evaluate_email_security
from src.app.security.scope_enforcement import optional_connector_read


router = APIRouter(prefix="/api/v1/ingest/m365", tags=["ingest-m365"])


def _check_secret(secret: str | None) -> None:
    expected = os.getenv("M365_INGEST_SECRET") or os.getenv("EMAIL_INGEST_SECRET") or ""
    if not expected:
        raise HTTPException(status_code=503, detail="ingest_secret_not_configured")
    if not secret or not hmac.compare_digest(str(secret), str(expected)):
        raise HTTPException(status_code=401, detail="invalid_secret")


@router.post("/notifications", response_class=PlainTextResponse)
async def notifications(
    request: Request,
    validationToken: Optional[str] = None,  # Microsoft uses this exact casing
    x_ingest_secret: Optional[str] = Header(default=None, alias="X-Ingest-Secret"),
    _scopes=Depends(optional_connector_read()),
):
    """Receive Microsoft Graph subscription notifications.

    Supports the subscription validation handshake via `validationToken`.
    For actual notifications, verifies a shared secret header and (optionally) `clientState`.
    """
    if validationToken:
        # Graph requires echoing the token as plain text.
        return validationToken

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

    record_email_security_connector_event(tenant_id, "m365")

    # Allow direct canonical payload from connector workers:
    email = payload.get("email") if isinstance(payload, dict) else None
    if isinstance(email, dict) and email.get("from_addr"):
        email = dict(email)
        email["provider"] = "m365"
        evaluate_email_security(email, tenant_id=tenant_id)
        return "ok"

    # Best-effort verification of clientState when configured.
    expected_state = os.getenv("M365_CLIENT_STATE")
    if expected_state:
        try:
            vals = payload.get("value") if isinstance(payload.get("value"), list) else []
            for v in vals:
                cs = (v or {}).get("clientState")
                if cs and not hmac.compare_digest(str(cs), str(expected_state)):
                    record_email_security_connector_failure(tenant_id, "m365", "client_state_mismatch")
                    raise HTTPException(status_code=401, detail="client_state_mismatch")
        except HTTPException:
            raise
        except Exception:
            pass

    # Notification-only mode; enqueue message id/resource for worker fetch.
    try:
        vals = payload.get("value") if isinstance(payload.get("value"), list) else []
        for v in vals:
            rd = (v or {}).get("resourceData") if isinstance(v, dict) else None
            msg_id = (rd or {}).get("id") if isinstance(rd, dict) else None
            resource = (v or {}).get("resource") if isinstance(v, dict) else None
            if msg_id:
                from src.app.deps import get_redis

                r = get_redis()
                if r.__class__.__name__ == "DummyRedis":
                    raise HTTPException(status_code=503, detail="redis_required_for_notification_mode")
                r.lpush(
                    "q:email:m365",
                    __import__("json").dumps(
                        {
                            "tenant_id": tenant_id,
                            "message_id": str(msg_id),
                            "resource": str(resource or ""),
                        }
                    ),
                )
    except HTTPException:
        raise
    except Exception:
        record_email_security_connector_failure(tenant_id, "m365", "enqueue_error")

    # Notification-only mode; actual message fetch happens in connector workers.
    return "ok"
