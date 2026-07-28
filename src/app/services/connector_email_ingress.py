from __future__ import annotations

from typing import Any, Dict

from src.app.services.email_connector_identity import (
    ConnectorIdentity,
    identity_mode,
    resolve_subscription,
)


def identity_for_worker_item(
    provider: str,
    item: Dict[str, Any],
) -> ConnectorIdentity:
    """Resolve queue metadata to authoritative connector identity."""
    provider_key = str(provider or "").strip().lower()
    subscription_id = str(
        item.get("subscription_id")
        or item.get("subscriptionId")
        or item.get("subscription")
        or ""
    ).strip()
    if identity_mode() == "strict":
        identity = resolve_subscription(provider_key, subscription_id)
        claimed = str(item.get("tenant_id") or "").strip()
        if claimed and claimed != identity.tenant_id:
            raise ValueError("tenant_subscription_mismatch")
        return identity
    if subscription_id:
        try:
            return resolve_subscription(provider_key, subscription_id)
        except Exception:
            pass
    tenant_id = str(item.get("tenant_id") or "").strip()
    if not tenant_id:
        raise ValueError("tenant_id_required")
    return ConnectorIdentity(
        provider=provider_key,
        subscription_id=subscription_id or "dev-direct",
        tenant_id=tenant_id,
        config={},
    )


def persist_connector_email(
    identity: ConnectorIdentity,
    email: Dict[str, Any],
) -> Dict[str, Any]:
    from src.app.models.db import db_session
    from src.app.services.inbound_email_inbox import ingest_email

    payload = dict(email or {})
    payload["provider"] = identity.provider
    payload["tenant_id"] = identity.tenant_id
    with db_session() as db:
        result = ingest_email(
            db,
            provider=identity.provider,
            tenant_id=identity.tenant_id,
            email=payload,
            subscription_id=identity.subscription_id,
            fulfillment_case_id=payload.get("fulfillment_case_id"),
        )
        db.commit()
        return result
