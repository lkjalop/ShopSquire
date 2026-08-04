from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import text


@dataclass(frozen=True)
class OperatorTenantIdentity:
    principal_hash: str
    tenant_id: str
    role: str
    subject_id: str
    auth_method: str
    persisted: bool


def membership_mode() -> str:
    configured = str(os.getenv("OPERATOR_TENANT_MEMBERSHIP_MODE") or "").strip().lower()
    if configured in {"strict", "audit"}:
        return configured
    env = str(os.getenv("APP_ENV") or "dev").strip().lower()
    return "strict" if env in {"prod", "production", "staging"} else "audit"


def principal_hash_for_api_key(api_key: str) -> str:
    value = str(api_key or "")
    if not value:
        raise ValueError("api_key_required")
    return hashlib.sha256(f"api_key\0{value}".encode("utf-8")).hexdigest()


def principal_hash_for_subject(subject_id: str, *, issuer: str = "") -> str:
    subject = str(subject_id or "").strip()
    if not subject:
        raise ValueError("operator_subject_required")
    namespace = str(issuer or "shopsquire").strip()
    return hashlib.sha256(
        f"bearer\0{namespace}\0{subject}".encode("utf-8")
    ).hexdigest()


def grant_membership(
    db,
    *,
    principal_hash: str,
    tenant_id: str,
    role: str,
    subject_id: str = "",
    auth_method: str,
    created_by: str,
) -> None:
    now = datetime.now(timezone.utc)
    values = {
        "principal": str(principal_hash),
        "tenant": str(tenant_id).strip(),
        "role": str(role).strip(),
        "subject": str(subject_id or "").strip() or None,
        "method": str(auth_method).strip(),
        "created_by": str(created_by).strip(),
        "now": now,
    }
    if not values["tenant"] or not values["role"] or not values["created_by"]:
        raise ValueError("membership_fields_required")
    existing = db.execute(
        text(
            "SELECT 1 FROM operator_tenant_membership "
            "WHERE principal_hash=:principal AND tenant_id=:tenant"
        ),
        values,
    ).fetchone()
    if existing:
        db.execute(
            text(
                "UPDATE operator_tenant_membership SET role=:role, subject_id=:subject, "
                "auth_method=:method, status='active', updated_at=:now, revoked_at=NULL "
                "WHERE principal_hash=:principal AND tenant_id=:tenant"
            ),
            values,
        )
    else:
        db.execute(
            text(
                "INSERT INTO operator_tenant_membership "
                "(principal_hash, tenant_id, role, subject_id, auth_method, status, "
                "created_by, created_at, updated_at) "
                "VALUES (:principal,:tenant,:role,:subject,:method,'active',"
                ":created_by,:now,:now)"
            ),
            values,
        )


def revoke_membership(
    db, *, principal_hash: str, tenant_id: str
) -> bool:
    now = datetime.now(timezone.utc)
    result = db.execute(
        text(
            "UPDATE operator_tenant_membership SET status='revoked', "
            "revoked_at=:now, updated_at=:now "
            "WHERE principal_hash=:principal AND tenant_id=:tenant AND status='active'"
        ),
        {
            "principal": str(principal_hash),
            "tenant": str(tenant_id).strip(),
            "now": now,
        },
    )
    return bool(result.rowcount)


def authorize_membership(
    db,
    *,
    principal_hash: str,
    tenant_id: str,
    authenticated_role: str,
    subject_id: str = "",
    auth_method: str,
    strict: Optional[bool] = None,
) -> OperatorTenantIdentity:
    tenant = str(tenant_id or "").strip()
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="tenant_scope_missing",
        )
    enforce = membership_mode() == "strict" if strict is None else bool(strict)
    try:
        row = db.execute(
            text(
                "SELECT role, subject_id, auth_method "
                "FROM operator_tenant_membership "
                "WHERE principal_hash=:principal AND tenant_id=:tenant "
                "AND status='active'"
            ),
            {"principal": str(principal_hash), "tenant": tenant},
        ).fetchone()
    except Exception:
        if enforce:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="operator_tenant_membership_unavailable",
            )
        row = None
    if row and str(row[0]) not in {str(authenticated_role), "*"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="operator_tenant_role_mismatch",
        )
    if not row and enforce:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="operator_tenant_membership_required",
        )
    return OperatorTenantIdentity(
        principal_hash=str(principal_hash),
        tenant_id=tenant,
        role=str(authenticated_role),
        subject_id=str((row[1] if row else subject_id) or ""),
        auth_method=str((row[2] if row else auth_method) or ""),
        persisted=bool(row),
    )


def authorize_request_membership(
    *,
    request,
    role: str,
    effective_key: Optional[str],
    authorization: Optional[str],
    bearer_subject: Optional[str],
) -> OperatorTenantIdentity:
    from src.app.models.db import db_session
    from src.app.platform.tenant_context import current_tenant_id

    if effective_key:
        principal_hash = principal_hash_for_api_key(effective_key)
        subject_id = ""
        auth_method = "api_key"
    else:
        subject_id = str(bearer_subject or "").strip()
        issuer = str(
            os.getenv("OIDC_ISSUER")
            or os.getenv("JWT_ISSUER")
            or "shopsquire"
        )
        try:
            principal_hash = principal_hash_for_subject(subject_id, issuer=issuer)
        except ValueError:
            if membership_mode() == "strict":
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="authenticated_operator_subject_required",
                )
            # Audit/dev mode still avoids persisting or exposing the bearer token.
            principal_hash = hashlib.sha256(
                b"bearer-without-subject"
            ).hexdigest()
        auth_method = "bearer"
    tenant_id = str(current_tenant_id() or "").strip()
    with db_session() as db:
        identity = authorize_membership(
            db,
            principal_hash=principal_hash,
            tenant_id=tenant_id,
            authenticated_role=role,
            subject_id=subject_id,
            auth_method=auth_method,
        )
    if request is not None:
        request.state.operator_identity = identity
    return identity
