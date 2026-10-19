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
    try:
        bindings = json.loads(os.getenv("BUYER_TENANT_BINDINGS_JSON", "{}") or "{}")
        if not isinstance(bindings, dict):
            return False
        if subject in bindings:
            allowed = bindings[subject]
            return isinstance(allowed, list) and tenant_id in {str(value) for value in allowed}
    except (TypeError, ValueError, json.JSONDecodeError):
        return False
    try:
        with db_session() as db:
            row = db.execute(text('SELECT tenant_id,tenant_ownership_status FROM customers WHERE id=:subject'),
                             {'subject':subject}).first()
        if row and row[1] == 'authenticated_request_context':
            # Native registration records ownership in the authorized request
            # context. A caller-supplied tenant/UID alone cannot create this row.
            return str(row[0]) == tenant_id
    except Exception:
        # An unavailable membership store cannot establish that a signed buyer
        # belongs to default rather than a different native storefront.
        return False
    return tenant_id == 'default'


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


async def require_shopping_case_principal(request: Request) -> BuyerPrincipal:
    """Authenticate the entire buyer-case surface, including reads and creation.

    Compatibility UIDs cannot establish ownership even in a fictional shop.
    FastAPI reuses the cached request body for subsequent schema validation.
    """
    supplied_uid=request.query_params.get('uid')
    if request.method in {'POST','PUT','PATCH','DELETE'}:
        try:
            body=await request.json()
        except (ValueError,TypeError):
            body=None
        if isinstance(body,dict) and body.get('uid') is not None:
            if supplied_uid is not None and supplied_uid!=body['uid']:
                raise HTTPException(status_code=403,detail='buyer_identity_mismatch')
            supplied_uid=body['uid']
    principal=resolve_buyer_principal(request,supplied_uid=supplied_uid)
    if principal is None or not principal.verified:
        raise HTTPException(status_code=401,detail='verified_buyer_identity_required')
    requested_tenant=str(request.headers.get('x-tenant-id') or 'default').strip() or 'default'
    if requested_tenant!=principal.tenant_id:
        raise HTTPException(status_code=403,detail='buyer_tenant_context_mismatch')
    request.state.buyer_principal=principal
    return principal


async def require_buyer_or_operator(request: Request) -> str:
    """Own-UID buyer access for chat/cart; retain explicit operator credentials.

    A native buyer session is not an operator role. Reuse the same signed
    identity and tenant checks used by the shopping-case surface.
    """
    key = request.headers.get('x-api-key') or request.cookies.get('shopsquire_api_key')
    authorization = request.headers.get('authorization')
    if not key and (_verified_access_subject(request) or _session_subject(request)):
        await require_shopping_case_principal(request)
        uid = request.query_params.get('uid')
        if request.method in {'POST', 'PUT', 'PATCH', 'DELETE'}:
            try:
                body = await request.json()
            except (ValueError, TypeError):
                body = None
            if isinstance(body, dict):uid = body.get('uid', uid)
        if not uid:
            raise HTTPException(status_code=400, detail='buyer_uid_required')
        return 'buyer'
    from src.app.security.auth import require_role, ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER
    return require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER])(
        x_api_key=key, authorization=authorization, request=request)
