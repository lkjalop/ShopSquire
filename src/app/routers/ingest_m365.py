from __future__ import annotations

import hmac
import os
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import PlainTextResponse

from src.app.observability.metrics import record_email_security_connector_event, record_email_security_connector_failure
from src.app.security.email_security import evaluate_email_security
from src.app.services.email_connector_identity import (
    ConnectorIdentity,
    identity_mode,
    resolve_subscription,
    verify_m365_notification,
)
router = APIRouter(prefix="/api/v1/ingest/m365", tags=["ingest-m365"])


def _check_secret(secret: str | None) -> None:
    expected = os.getenv("M365_INGEST_SECRET") or os.getenv("EMAIL_INGEST_SECRET") or ""
    if not expected:
        raise HTTPException(status_code=503, detail="ingest_secret_not_configured")
    if not secret or not hmac.compare_digest(str(secret), str(expected)):
        raise HTTPException(status_code=401, detail="invalid_secret")


def _persist_or_evaluate(identity: ConnectorIdentity, email: dict) -> dict:
    try:
        from src.app.models.db import db_session
        from src.app.services.inbound_email_inbox import ingest_email

        with db_session() as db:
            result = ingest_email(
                db,
                provider="m365",
                tenant_id=identity.tenant_id,
                email=email,
                subscription_id=identity.subscription_id,
                fulfillment_case_id=email.get("fulfillment_case_id"),
            )
            db.commit()
            return result
    except Exception as exc:
        if identity_mode() == "strict":
            record_email_security_connector_failure(identity.tenant_id, "m365", "inbox_unavailable")
            raise HTTPException(status_code=503, detail="inbound_email_inbox_unavailable") from exc
        verdict = evaluate_email_security(email, tenant_id=identity.tenant_id)
        return {"status": "evaluated_not_persisted", "security_route": verdict.get("route")}


@router.post("/notifications", response_class=PlainTextResponse)
async def notifications(
    request: Request,
    validationToken: Optional[str] = None,  # Microsoft uses this exact casing
    x_ingest_secret: Optional[str] = Header(default=None, alias="X-Ingest-Secret"),
):
    """Receive Microsoft Graph subscription notifications.

    Supports the subscription validation handshake via `validationToken`.
    For actual notifications, verifies a shared secret header and (optionally) `clientState`.
    """
    if validationToken:
        # Graph requires echoing the token as plain text.
        return validationToken

    try:
        payload = await request.json()
    except Exception:
        payload = {}

    vals = payload.get("value") if isinstance(payload.get("value"), list) else []
    if identity_mode() == "strict":
        if not vals:
            raise HTTPException(status_code=401, detail="m365_subscription_required")
        identities = []
        try:
            for value in vals:
                identity = resolve_subscription("m365", str((value or {}).get("subscriptionId") or ""))
                verify_m365_notification(identity, value or {})
                identities.append(identity)
        except Exception as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        if len({identity.tenant_id for identity in identities}) != 1:
            raise HTTPException(status_code=403, detail="mixed_tenant_notification_batch")
        identity = identities[0]
        claimed = str(payload.get("tenant_id") or request.headers.get("X-Tenant-Id") or "").strip()
        if claimed and claimed != identity.tenant_id:
            raise HTTPException(status_code=403, detail="tenant_subscription_mismatch")
    else:
        _check_secret(x_ingest_secret)
        tenant_id = str(payload.get("tenant_id") or request.headers.get("X-Tenant-Id") or "").strip()
        if not tenant_id:
            raise HTTPException(status_code=400, detail="tenant_id_required")
        identity = ConnectorIdentity(
            "m365",
            str(payload.get("subscription_id") or "dev-direct"),
            tenant_id,
            {},
        )
    tenant_id = identity.tenant_id

    record_email_security_connector_event(tenant_id, "m365")

    # Allow direct canonical payload from connector workers:
    email = payload.get("email") if isinstance(payload, dict) else None
    if isinstance(email, dict) and email.get("from_addr"):
        email = dict(email)
        email["provider"] = "m365"
        _persist_or_evaluate(identity, email)
        return "ok"

    # Best-effort verification of clientState when configured.
    expected_state = os.getenv("M365_CLIENT_STATE")
    if identity_mode() != "strict" and expected_state:
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
