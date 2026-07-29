from __future__ import annotations

import base64
import hmac
import json
import logging
import os
from typing import Any, Dict, Optional

from fastapi import APIRouter, Header, HTTPException, Request

from src.app.observability.metrics import record_email_security_connector_event, record_email_security_connector_failure
from src.app.security.email_security import evaluate_email_security
from src.app.services.email_connector_identity import (
    identity_mode,
    resolve_subscription,
    verify_gmail_push_jwt,
)

router = APIRouter(prefix="/api/v1/ingest/gmail", tags=["ingest-gmail"])
logger = logging.getLogger("shopsquire.ingest_gmail")


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


def _identity(
    payload: Dict[str, Any],
    request: Request,
    *,
    authorization: Optional[str],
    secret: Optional[str],
):
    subscription_id = str(payload.get("subscription") or "").strip()
    if identity_mode() == "strict":
        try:
            identity = resolve_subscription("gmail", subscription_id)
            verify_gmail_push_jwt(
                authorization,
                audience=str(identity.config.get("audience") or ""),
                allowed_email=identity.config.get("service_account_email"),
            )
        except Exception as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        claimed = str(payload.get("tenant_id") or request.headers.get("X-Tenant-Id") or "").strip()
        if claimed and claimed != identity.tenant_id:
            raise HTTPException(status_code=403, detail="tenant_subscription_mismatch")
        return identity

    _check_secret(secret)
    tenant_id = str(payload.get("tenant_id") or request.headers.get("X-Tenant-Id") or "").strip()
    if not tenant_id:
        raise HTTPException(status_code=400, detail="tenant_id_required")
    from src.app.services.email_connector_identity import ConnectorIdentity

    return ConnectorIdentity("gmail", subscription_id or "dev-direct", tenant_id, {})


def _persist_or_evaluate(identity, email: Dict[str, Any]) -> Dict[str, Any]:
    try:
        from src.app.models.db import db_session
        from src.app.services.inbound_email_inbox import ingest_email

        with db_session() as db:
            result = ingest_email(
                db,
                provider="gmail",
                tenant_id=identity.tenant_id,
                email=email,
                subscription_id=identity.subscription_id,
                fulfillment_case_id=email.get("fulfillment_case_id"),
            )
            if identity_mode() == "strict" and result.get("inbox_id"):
                from src.app.services.supplier_observation_projection import (
                    project_governed_supplier_inbox,
                )

                result["supply_projection"] = project_governed_supplier_inbox(
                    db,
                    inbox_id=result["inbox_id"],
                    connector_identity=identity,
                    transport_identity_verified=True,
                )
            db.commit()
            return result
    except Exception as exc:
        if identity_mode() == "strict":
            record_email_security_connector_failure(identity.tenant_id, "gmail", "inbox_unavailable")
            raise HTTPException(status_code=503, detail="inbound_email_inbox_unavailable") from exc
        logger.warning(
            "gmail inbox persistence unavailable; evaluating without custody tenant=%s error=%s",
            identity.tenant_id,
            repr(exc)[:180],
        )
        verdict = evaluate_email_security(email, tenant_id=identity.tenant_id)
        return {"status": "evaluated_not_persisted", "security_route": verdict.get("route")}


@router.post("/pubsub")
async def pubsub_push(
    request: Request,
    x_ingest_secret: Optional[str] = Header(default=None, alias="X-Ingest-Secret"),
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
):
    """Receive Gmail push notifications (typically via Google Pub/Sub push).

    Production uses Google OIDC push identity and an authoritative subscription
    registry. Shared-secret direct payloads are restricted to dev/test mode.
    """
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    identity = _identity(
        payload if isinstance(payload, dict) else {},
        request,
        authorization=authorization,
        secret=x_ingest_secret,
    )
    tenant_id = identity.tenant_id

    record_email_security_connector_event(tenant_id, "gmail")

    # Allow a direct canonical email payload for MVP/demo connector workers:
    email = payload.get("email") if isinstance(payload, dict) else None
    if isinstance(email, dict) and email.get("from_addr"):
        email = dict(email)
        email["provider"] = "gmail"
        _apply_supplier_domain_guard(email)
        result = _persist_or_evaluate(identity, email)
        return {"ok": True, **result}

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
                result = _persist_or_evaluate(identity, email2)
                return {"ok": True, **result}
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
                                "subscription_id": identity.subscription_id,
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
