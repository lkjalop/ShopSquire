from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class ConnectorIdentity:
    provider: str
    subscription_id: str
    tenant_id: str
    config: Dict[str, Any]


def identity_mode() -> str:
    configured = str(os.getenv("EMAIL_CONNECTOR_IDENTITY_MODE") or "").strip().lower()
    if configured in {"strict", "shared_secret"}:
        return configured
    env = str(os.getenv("APP_ENV") or "dev").strip().lower()
    return "strict" if env in {"prod", "production", "staging"} else "shared_secret"


def _registry() -> Dict[str, Any]:
    raw = str(os.getenv("EMAIL_CONNECTOR_SUBSCRIPTIONS_JSON") or "").strip()
    if not raw:
        return {}
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("EMAIL_CONNECTOR_SUBSCRIPTIONS_JSON must be an object")
    return parsed


def resolve_subscription(provider: str, subscription_id: str) -> ConnectorIdentity:
    provider_key = str(provider or "").strip().lower()
    subscription_key = str(subscription_id or "").strip()
    row = ((_registry().get(provider_key) or {}).get(subscription_key) or {})
    if not isinstance(row, dict) or not str(row.get("tenant_id") or "").strip():
        raise ValueError("unknown_connector_subscription")
    return ConnectorIdentity(
        provider=provider_key,
        subscription_id=subscription_key,
        tenant_id=str(row["tenant_id"]).strip(),
        config=dict(row),
    )


def verify_gmail_push_jwt(
    authorization: Optional[str],
    *,
    audience: str,
    allowed_email: Optional[str] = None,
) -> Dict[str, Any]:
    if not authorization or not str(authorization).startswith("Bearer "):
        raise ValueError("missing_google_push_bearer")
    token = str(authorization).split(" ", 1)[1].strip()
    if not token:
        raise ValueError("missing_google_push_bearer")
    import jwt

    jwks = jwt.PyJWKClient("https://www.googleapis.com/oauth2/v3/certs")
    key = jwks.get_signing_key_from_jwt(token).key
    claims = jwt.decode(
        token,
        key,
        algorithms=["RS256"],
        audience=str(audience),
        issuer=["https://accounts.google.com", "accounts.google.com"],
    )
    email = str(claims.get("email") or "").strip().lower()
    if allowed_email and email != str(allowed_email).strip().lower():
        raise ValueError("google_push_service_account_mismatch")
    if claims.get("email_verified") is False:
        raise ValueError("google_push_email_unverified")
    return dict(claims)


def verify_m365_notification(identity: ConnectorIdentity, notification: Dict[str, Any]) -> None:
    expected_state = str(identity.config.get("client_state") or "").strip()
    actual_state = str((notification or {}).get("clientState") or "").strip()
    if not expected_state or not actual_state:
        raise ValueError("m365_client_state_required")
    import hmac

    if not hmac.compare_digest(actual_state, expected_state):
        raise ValueError("m365_client_state_mismatch")
