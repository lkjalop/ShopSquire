"""Verified buyer identity and fulfillment ownership boundary.

Buyer identity is derived from a signed local access JWT or a server-stored
opaque session. Client-supplied UIDs are compatibility input only and are
rejected as authority in production.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import jwt
from fastapi import HTTPException, Request
from sqlalchemy import text

from src.app.models.db import db_session
from src.app.platform.tenant_context import current_tenant_id


@dataclass(frozen=True)
class BuyerPrincipal:
    subject: str
    tenant_id: str
    credential_kind: str
    verified: bool = True


def _strict_mode() -> bool:
    configured = str(os.getenv("BUYER_IDENTITY_MODE", "") or "").strip().lower()
    if configured in {"strict", "production"}:
        return True
    if configured in {"compat", "legacy", "off"}:
        return False
    return str(os.getenv("APP_ENV", "") or "").strip().lower() in {"prod", "production"}


def _tenant_allowed(subject: str, tenant_id: str) -> bool:
    if tenant_id == "default":
        return True
    try:
        bindings = json.loads(os.getenv("BUYER_TENANT_BINDINGS_JSON", "{}") or "{}")
        allowed = bindings.get(subject) if isinstance(bindings, dict) else None
        return isinstance(allowed, list) and tenant_id in {str(value) for value in allowed}
    except (TypeError, ValueError, json.JSONDecodeError):
        return False


def _verified_access_subject(request: Request) -> Optional[str]:
    authorization = str(request.headers.get("authorization") or "")
    token = (
        authorization.split(" ", 1)[1].strip()
        if authorization.lower().startswith("bearer ")
        else str(request.cookies.get("shopsquire_access") or "")
    )
    secret = str(os.getenv("JWT_SIGNING_KEY", "") or "").strip()
    if not token or not secret:
        return None
    try:
        claims = jwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            issuer=str(os.getenv("JWT_ISSUER", "shopsquire") or "shopsquire"),
            audience=str(os.getenv("JWT_AUDIENCE", "shopsquire-api") or "shopsquire-api"),
            options={"require": ["exp", "iat", "iss", "aud", "sub"]},
        )
    except jwt.PyJWTError:
        return None
    if str(claims.get("typ") or "").lower() != "access":
        return None
    return str(claims.get("sub") or "").strip() or None


def _session_subject(request: Request) -> Optional[str]:
    token = str(request.cookies.get("shopsquire_session") or "").strip()
    if not token:
        return None
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    try:
        with db_session() as db:
            row = db.execute(
                text(
                    "SELECT user_id, expires_at FROM session_tokens "
                    "WHERE token_hash=:token_hash OR token=:token LIMIT 1"
                ),
                {"token_hash": token_hash, "token": token},
            ).fetchone()
    except Exception:
        return None
    if not row:
        return None
    try:
        if row[1] and datetime.utcnow() > datetime.fromisoformat(str(row[1])):
            return None
    except (TypeError, ValueError):
        return None
    return str(row[0] or "").strip() or None


def resolve_buyer_principal(
    request: Request,
    *,
    supplied_uid: Optional[str] = None,
) -> Optional[BuyerPrincipal]:
    tenant_id = str(current_tenant_id() or "default")
    subject = _verified_access_subject(request)
    credential_kind = "access_jwt"
    if not subject:
        subject = _session_subject(request)
        credential_kind = "session"

    if subject:
        if supplied_uid and str(supplied_uid) != subject:
            raise HTTPException(status_code=403, detail="buyer_identity_mismatch")
        if not _tenant_allowed(subject, tenant_id):
            raise HTTPException(status_code=403, detail="buyer_tenant_not_authorized")
        return BuyerPrincipal(subject=subject, tenant_id=tenant_id, credential_kind=credential_kind)

    if _strict_mode():
        raise HTTPException(status_code=401, detail="verified_buyer_identity_required")
    if supplied_uid:
        return BuyerPrincipal(
            subject=str(supplied_uid),
            tenant_id=tenant_id,
            credential_kind="legacy_uid",
            verified=False,
        )
    return None


def assert_case_owner(db, case_id: str, principal: Optional[BuyerPrincipal]) -> None:
    """Return 404 for absent or foreign cases so the endpoint does not disclose IDs."""
    if principal is None:
        return
    row = db.execute(
        text(
            "SELECT buyer_uid_hash FROM fulfillment_case "
            "WHERE id=:case_id AND tenant_id=:tenant_id LIMIT 1"
        ),
        {"case_id": str(case_id), "tenant_id": principal.tenant_id},
    ).fetchone()
    if not row or str(row[0] or "") != principal.subject:
        raise HTTPException(status_code=404, detail="case not found")
