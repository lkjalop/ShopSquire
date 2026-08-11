from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import hmac
import json
import os
from typing import Any

from sqlalchemy import text

from src.app.models.db import db_session


@dataclass(frozen=True)
class SecurityConnectorIdentity:
    connector_id: str
    tenant_id: str
    provider: str
    allowed_event_families: tuple[str, ...]
    allowed_source_ids: tuple[str, ...]
    storage_targets: tuple[str, ...]
    response_actions: tuple[str, ...]


def _credential_hash(secret: str) -> str:
    pepper = str(os.getenv("SECURITY_CONNECTOR_CREDENTIAL_PEPPER") or "")
    environment = str(os.getenv("APP_ENV") or "dev").strip().lower()
    if not pepper and environment in {"prod", "production", "staging"}:
        raise RuntimeError("security_connector_credential_pepper_required")
    pepper = pepper or "local-security-connector-pepper"
    return hashlib.sha256(f"{pepper}:{secret}".encode("utf-8")).hexdigest()


def register_security_connector(
    *, connector_id: str, tenant_id: str, provider: str, bearer_secret: str,
    allowed_event_families: list[str], allowed_source_ids: list[str] | None = None,
    storage_targets: list[str] | None = None, response_actions: list[str] | None = None,
    credential_expires_at: str | None = None,
) -> dict[str, Any]:
    if not all(str(value or "").strip() for value in (connector_id, tenant_id, provider, bearer_secret)):
        raise ValueError("security_connector_identity_fields_required")
    families = sorted({str(item).strip().lower() for item in allowed_event_families if str(item).strip()})
    if not families:
        raise ValueError("security_connector_event_family_required")
    params = {
        "id": str(connector_id).strip(), "tenant": str(tenant_id).strip(), "provider": str(provider).strip().lower(),
        "credential": _credential_hash(str(bearer_secret)), "families": json.dumps(families),
        "sources": json.dumps(sorted({str(item).strip() for item in (allowed_source_ids or []) if str(item).strip()})),
        "storage": json.dumps(sorted({str(item).strip().lower() for item in (storage_targets or ["database"]) if str(item).strip()})),
        "actions": json.dumps(sorted({str(item).strip().lower() for item in (response_actions or ["alert"]) if str(item).strip()})),
        "expires": credential_expires_at,
    }
    with db_session() as db:
        existing = db.execute(text("SELECT 1 FROM security_connector_subscription WHERE connector_id=:id"), {"id": params["id"]}).fetchone()
        if existing:
            db.execute(text("""
                UPDATE security_connector_subscription SET tenant_id=:tenant, provider=:provider,
                  credential_hash=:credential, allowed_event_families_json=:families,
                  allowed_source_ids_json=:sources, permitted_storage_targets_json=:storage,
                  permitted_response_actions_json=:actions, credential_expires_at=:expires,
                  status='active', updated_at=CURRENT_TIMESTAMP WHERE connector_id=:id
            """), params)
        else:
            db.execute(text("""
                INSERT INTO security_connector_subscription
                  (connector_id, tenant_id, provider, credential_hash, allowed_event_families_json,
                   allowed_source_ids_json, permitted_storage_targets_json, permitted_response_actions_json,
                   status, credential_expires_at)
                VALUES (:id,:tenant,:provider,:credential,:families,:sources,:storage,:actions,'active',:expires)
            """), params)
        db.commit()
    return {"connector_id": params["id"], "tenant_id": params["tenant"], "provider": params["provider"], "allowed_event_families": families}


def authenticate_security_connector(*, connector_id: str, bearer_secret: str, event_family: str, source_id: str | None = None) -> SecurityConnectorIdentity:
    with db_session() as db:
        row = db.execute(text("""
            SELECT connector_id, tenant_id, provider, credential_hash, allowed_event_families_json,
                   allowed_source_ids_json, permitted_storage_targets_json, permitted_response_actions_json,
                   status, credential_expires_at
            FROM security_connector_subscription WHERE connector_id=:id
        """), {"id": str(connector_id or "").strip()}).fetchone()
        if not row or str(row[8] or "") != "active":
            raise ValueError("unknown_security_connector")
        if not hmac.compare_digest(str(row[3] or ""), _credential_hash(str(bearer_secret or ""))):
            raise ValueError("invalid_security_connector_credential")
        if row[9]:
            expires = datetime.fromisoformat(str(row[9]).replace("Z", "+00:00"))
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=timezone.utc)
            if expires <= datetime.now(timezone.utc):
                raise ValueError("expired_security_connector_credential")
        families = tuple(json.loads(str(row[4] or "[]")))
        sources = tuple(json.loads(str(row[5] or "[]")))
        requested_family = str(event_family or "").strip().lower()
        if requested_family not in families:
            raise ValueError("security_connector_event_family_denied")
        if sources and str(source_id or "").strip() not in sources:
            raise ValueError("security_connector_source_denied")
        db.execute(text("UPDATE security_connector_subscription SET last_seen_at=CURRENT_TIMESTAMP, updated_at=CURRENT_TIMESTAMP WHERE connector_id=:id"), {"id": row[0]})
        db.commit()
    return SecurityConnectorIdentity(
        connector_id=str(row[0]), tenant_id=str(row[1]), provider=str(row[2]),
        allowed_event_families=families, allowed_source_ids=sources,
        storage_targets=tuple(json.loads(str(row[6] or "[]"))),
        response_actions=tuple(json.loads(str(row[7] or "[]"))),
    )
