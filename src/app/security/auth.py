from __future__ import annotations

import json
import os
import time
import uuid
import ipaddress
import base64
import hmac
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

from fastapi import Header, HTTPException, status, Request
from typing import Callable, Dict
from sqlalchemy import text as sql_text

from src.app.deps import get_redis
from src.app.models.db import db_session

_JWKS_CACHE: Dict[str, Dict] = {}
_JWKS_FETCHED_AT: Dict[str, float] = {}
_INTROSPECTION_CACHE: Dict[str, tuple[float, dict]] = {}
_INTROSPECTION_TTL = int(os.getenv("OIDC_INTROSPECTION_TTL_SEC", "30") or 30)
_JWKS_CACHE_TTL = int(os.getenv("OIDC_JWKS_CACHE_TTL_SEC", "300") or 300)


def _failed_auth_limit_per_hour() -> int:
    try:
        return max(1, int(float(os.getenv("FAILED_AUTH_IP_LIMIT_PER_HOUR", "50") or 50)))
    except Exception:
        return 50


def _failed_auth_ttl_seconds() -> int:
    try:
        return max(60, int(float(os.getenv("FAILED_AUTH_IP_WINDOW_SECONDS", "3600") or 3600)))
    except Exception:
        return 3600


def _auth_lockout_enabled() -> bool:
    return str(os.getenv("FAILED_AUTH_IP_LOCKOUT_ENABLED", "1") or "1").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _auth_bucket(now: float | None = None) -> int:
    ts = float(now if now is not None else time.time())
    return int(ts // _failed_auth_ttl_seconds())


def _auth_ip_key(ip: str | None) -> str:
    return f"auth:failed_ip:{_auth_bucket()}:{str(ip or 'unknown')}"


def _is_ip_locked_out(ip: str | None) -> tuple[bool, int]:
    if not _auth_lockout_enabled():
        return False, 0
    try:
        r = get_redis()
        count = int(float(r.get(_auth_ip_key(ip)) or 0.0))
    except Exception:
        count = 0
    limit = _failed_auth_limit_per_hour()
    return count >= limit, max(0, limit - count)


def _record_failed_auth(ip: str | None) -> None:
    if not _auth_lockout_enabled():
        return
    try:
        r = get_redis()
        key = _auth_ip_key(ip)
        try:
            r.incrby(key, 1)
            r.expire(key, _failed_auth_ttl_seconds() + 60)
        except Exception:
            pass
    except Exception:
        pass


def _clear_failed_auth(ip: str | None) -> None:
    if not _auth_lockout_enabled():
        return
    try:
        get_redis().delete(_auth_ip_key(ip))
    except Exception:
        pass


def _bearer_subject(auth_header: Optional[str]) -> Optional[str]:
    if not auth_header or not auth_header.lower().startswith("bearer "):
        return None
    token = auth_header.split(" ", 1)[1].strip()
    # Local JWT path
    try:
        parts = token.split(".")
        if len(parts) == 3:
            p = parts[1]
            pad = "=" * ((4 - len(p) % 4) % 4)
            claims = json.loads(base64.urlsafe_b64decode((p + pad).encode("ascii")).decode("utf-8"))
            sub = claims.get("sub") or claims.get("user_id") or claims.get("uid")
            if sub:
                return str(sub)
    except Exception:
        pass
    # Introspection fallback
    try:
        data = _introspect_token(auth_header)
        if isinstance(data, dict):
            sub = data.get("sub") or data.get("uid") or data.get("user_id")
            if sub:
                return str(sub)
    except Exception:
        pass
    return None


def _bearer_email(auth_header: Optional[str]) -> Optional[str]:
    """The email claim from a bearer (local JWT, else introspection), or None. Best-effort, never raises."""
    if not auth_header or not auth_header.lower().startswith("bearer "):
        return None
    token = auth_header.split(" ", 1)[1].strip()
    try:
        parts = token.split(".")
        if len(parts) == 3:
            p = parts[1]
            pad = "=" * ((4 - len(p) % 4) % 4)
            claims = json.loads(base64.urlsafe_b64decode((p + pad).encode("ascii")).decode("utf-8"))
            if claims.get("email"):
                return str(claims["email"])
    except Exception:
        pass
    try:
        data = _introspect_token(auth_header)
        if isinstance(data, dict) and data.get("email"):
            return str(data["email"])
    except Exception:
        pass
    return None


@dataclass
class OperatorSubject:
    """Best-effort per-user identity for AUDIT attribution (not authorization). user_id='' when only a shared
    API key is used — the caller stamps a 'key:<role>' sentinel so the trail still shows 'shared key, no user'."""
    user_id: str = ""
    email: str = ""


def operator_subject(authorization: Optional[str] = Header(default=None, alias="Authorization")) -> OperatorSubject:
    """FastAPI dependency: extract the JWT subject + email for per-user audit attribution. Does NOT enforce
    auth — pair it with require_role, which does. Ready to capture a real operator the moment an IdP issues
    JWTs; until then it returns empty and the caller falls back to a role sentinel."""
    return OperatorSubject(user_id=_bearer_subject(authorization) or "", email=_bearer_email(authorization) or "")


def _authorize_operator_tenant(
    *,
    request: Optional[Request],
    role: str,
    effective_key: Optional[str],
    authorization: Optional[str],
) -> None:
    """Bind the authenticated credential to a persisted tenant membership.

    The request header selects a tenant context; it never grants that context.
    Production/staging fail closed when membership storage or membership is absent.
    """
    if request is None:
        return
    from src.app.services.operator_tenant_membership import (
        authorize_request_membership,
    )

    authorize_request_membership(
        request=request,
        role=role,
        effective_key=effective_key,
        authorization=authorization,
        bearer_subject=_bearer_subject(authorization),
    )


def _assert_privileged_role_server_side(*, role: str, authorization: Optional[str], effective_key: Optional[str]) -> bool:
    """§10 hardening: never trust privileged role solely from JWT claims.

    - API key roles are server-side by construction and pass.
    - Bearer-derived owner/developer roles require subject lookup in `user_accounts`.
    """
    if role not in (ROLE_OWNER, ROLE_DEVELOPER):
        return True
    if effective_key:
        return True
    subj = _bearer_subject(authorization)
    if not subj:
        return False
    try:
        with db_session() as db:
            row = db.execute(
                sql_text("SELECT 1 FROM user_accounts WHERE id = :id LIMIT 1"),
                {"id": subj},
            ).fetchone()
            return bool(row)
    except Exception:
        return False


def _abac_enabled() -> bool:
    explicit = str(os.getenv("ABAC_ENABLED", "") or "").lower()
    if explicit in ("1", "true", "yes", "on"):
        return True
    if explicit in ("0", "false", "no", "off"):
        return False
    env = str(os.getenv("APP_ENV", "") or "").lower()
    return env in ("prod", "production")


def _resource_sensitivity(path: str) -> str:
    p = str(path or "").lower()
    if p.startswith("/api/v1/admin") or p.startswith("/api/v1/security") or p.startswith("/api/v1/connectors"):
        return "high"
    if p.startswith("/api/v1/tickets") or p.startswith("/api/v1/tools"):
        return "medium"
    return "low"


def _parse_utc_hour_range(raw: str) -> tuple[int, int] | None:
    try:
        parts = str(raw or "").split("-")
        if len(parts) != 2:
            return None
        a = int(parts[0])
        b = int(parts[1])
        if 0 <= a <= 23 and 0 <= b <= 23:
            return a, b
    except Exception:
        return None
    return None


def _hour_in_range(hour: int, start: int, end: int) -> bool:
    if start <= end:
        return start <= hour <= end
    return hour >= start or hour <= end


def _split_csv(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [x.strip() for x in str(raw).split(",") if str(x).strip()]


def _ip_in_any(ip: str | None, cidrs: list[str]) -> bool:
    if not ip or not cidrs:
        return False
    try:
        ip_obj = ipaddress.ip_address(str(ip))
    except Exception:
        return False
    for c in cidrs:
        try:
            if ip_obj in ipaddress.ip_network(c, strict=False):
                return True
        except Exception:
            continue
    return False


def _abac_tenant_allow(role: str, tenant_id: str | None) -> bool:
    raw = os.getenv("ABAC_TENANT_ALLOWLIST_JSON", "")
    if not raw:
        return True
    try:
        doc = json.loads(raw)
        if not isinstance(doc, dict):
            return True
        allowed = doc.get(role)
        if not isinstance(allowed, list) or not allowed:
            return True
        return str(tenant_id or "") in [str(x) for x in allowed]
    except Exception:
        # P0-2: a CONFIGURED but malformed allowlist must not silently become allow-all — that
        # disables the tenant restriction the operator set. Fail CLOSED (deny) so a broken config is
        # a loud denial, never a silent cross-tenant hole. (Empty/unset allowlist above allows all.)
        return False


def _parse_mfa_verified_at(value: str | None) -> float | None:
    if not value:
        return None
    s = str(value).strip()
    try:
        # epoch seconds
        if s.isdigit():
            return float(int(s))
        # ISO timestamp
        from datetime import datetime as _dt
        return _dt.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def _emit_abac_deny_trace(request: Optional[Request], role: str | None, reason: str, details: dict) -> None:
    try:
        from src.app.services.decision_log import log_trace_event
        rid = (
            (request.headers.get("x-trace-id") if request else None)
            or (request.headers.get("x-correlation-id") if request else None)
            or f"abac-{uuid.uuid4()}"
        )
        log_trace_event(
            trace_id=rid,
            event_type="policy_gate",
            source_type="policy_gate",
            source_id="ABAC_Gate_Agent",
            target_type="system",
            target_id=None,
            payload={
                "decision": "deny",
                "reason": "abac_policy_violation",
                "abac_reason": reason,
                "role": role,
                "resource": details.get("resource"),
                "tenant_id": details.get("tenant_id"),
                "source_ip": details.get("source_ip"),
                "environment": details.get("environment"),
            },
        )
    except Exception:
        pass


def _evaluate_abac(
    *,
    role: str,
    request: Optional[Request],
) -> tuple[bool, str | None, dict]:
    path = getattr(getattr(request, "url", None), "path", "") if request else ""
    method = getattr(request, "method", "") if request else ""
    sensitivity = _resource_sensitivity(path)
    tenant_id = (
        (request.headers.get("x-tenant-id") if request else None)
        or (request.query_params.get("tenant_id") if request else None)
    )
    source_ip = request.client.host if request and request.client else None
    env = str(os.getenv("APP_ENV", "local") or "local").lower()

    details = {
        "resource": {"path": path, "method": method, "sensitivity": sensitivity},
        "tenant_id": tenant_id,
        "source_ip": source_ip,
        "environment": env,
    }

    # Tenant binding for sensitive resources.
    if sensitivity in ("medium", "high") and not tenant_id:
        return False, "missing_tenant_scope", details
    if not _abac_tenant_allow(role, tenant_id):
        return False, "tenant_not_allowed_for_role", details

    # Source IP controls.
    blocked_ips = _split_csv(os.getenv("ABAC_BLOCKED_SOURCE_IPS"))
    if source_ip and source_ip in blocked_ips:
        return False, "blocked_source_ip", details
    blocked_cidrs = _split_csv(os.getenv("ABAC_BLOCKED_SOURCE_CIDRS"))
    if _ip_in_any(source_ip, blocked_cidrs):
        return False, "blocked_source_cidr", details
    high_risk_ips = _split_csv(os.getenv("ABAC_HIGH_RISK_SOURCE_IPS"))
    if sensitivity == "high" and source_ip and source_ip in high_risk_ips:
        return False, "high_risk_source_ip_for_sensitive_resource", details

    # Time-of-day window (UTC) for sensitive operations in production.
    if env in ("prod", "production") and sensitivity == "high":
        window_raw = os.getenv("ABAC_ALLOWED_HOURS_UTC", "06-22")
        hr = _parse_utc_hour_range(window_raw)
        if hr:
            from datetime import datetime as _dt, timezone as _tz
            cur_h = _dt.now(_tz.utc).hour
            if not _hour_in_range(cur_h, hr[0], hr[1]):
                return False, "outside_allowed_operating_hours_utc", details

    # MFA freshness for sensitive resources.
    if sensitivity == "high":
        max_age = int(os.getenv("ABAC_MFA_MAX_AGE_SECONDS", "900") or 900)
        mfa_verified_at = _parse_mfa_verified_at(request.headers.get("x-mfa-verified-at") if request else None)
        if not mfa_verified_at:
            return False, "mfa_freshness_missing", details
        now_ts = time.time()
        if (now_ts - float(mfa_verified_at)) > float(max_age):
            return False, "mfa_freshness_expired", details

    return True, None, details


def _admin_oidc_required() -> bool:
    explicit = str(os.getenv("ADMIN_OIDC_REQUIRED", "") or "").lower()
    if explicit in ("1", "true", "yes", "on"):
        return True
    if explicit in ("0", "false", "no", "off"):
        return False
    env = str(os.getenv("APP_ENV", "") or "").lower()
    return env in ("prod", "production")


def _is_admin_operator_scope(allowed: set[str]) -> bool:
    return (ROLE_OWNER in allowed) or (ROLE_DEVELOPER in allowed)


def _verify_local_jwt(auth_header: Optional[str]) -> Optional[str]:
    """Validate locally-issued HS256 access JWTs and return role claim."""
    if not auth_header or not auth_header.lower().startswith("bearer "):
        return None
    secret = str(os.getenv("JWT_SIGNING_KEY", "") or "").strip()
    if not secret:
        return None
    token = auth_header.split(" ", 1)[1].strip()
    issuer = str(os.getenv("JWT_ISSUER", "shopsquire") or "shopsquire")
    audience = str(os.getenv("JWT_AUDIENCE", "shopsquire-api") or "shopsquire-api")
    role_claim = str(os.getenv("JWT_ROLE_CLAIM", "role") or "role")
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        h, p, s = parts
        sig = base64.urlsafe_b64encode(
            hmac.new(secret.encode("utf-8"), f"{h}.{p}".encode("utf-8"), hashlib.sha256).digest()
        ).decode("ascii").rstrip("=")
        if not hmac.compare_digest(sig, s):
            return None
        pad = "=" * ((4 - len(p) % 4) % 4)
        claims = json.loads(base64.urlsafe_b64decode((p + pad).encode("ascii")).decode("utf-8"))
        now = int(time.time())
        exp = int(claims.get("exp") or 0)
        iat = int(claims.get("iat") or 0)
        if exp <= now or iat > now + 5:
            return None
        if str(claims.get("iss") or "") != issuer:
            return None
        aud_val = claims.get("aud")
        if isinstance(aud_val, list):
            if audience not in [str(x) for x in aud_val]:
                return None
        elif str(aud_val or "") != audience:
            return None
        token_type = str(claims.get("typ") or claims.get("token_type") or "access").lower()
        if token_type != "access":
            return None
        role = claims.get(role_claim)
        if isinstance(role, list):
            role = role[0] if role else None
        return str(role) if role else None
    except Exception:
        return None


def _verify_oidc_jwt(auth_header: Optional[str]) -> Optional[str]:
    """Return role from JWT claims if OIDC configured and token valid; otherwise None.

    Environment:
      - OIDC_JWKS_URL: JWKS endpoint
      - OIDC_ISSUER: expected issuer
      - OIDC_AUDIENCE: expected audience
      - OIDC_ROLE_CLAIM: claim name for role (default: 'role')
    """
    try:
        import jwt  # PyJWT
        import requests as _req
    except Exception:
        return None
    if not auth_header or not auth_header.lower().startswith("bearer "):
        return None
    token = auth_header.split(" ", 1)[1].strip()
    jwks_url = os.getenv("OIDC_JWKS_URL")
    issuer = os.getenv("OIDC_ISSUER")
    audience = os.getenv("OIDC_AUDIENCE")
    role_claim = os.getenv("OIDC_ROLE_CLAIM", "role")
    if not jwks_url:
        return None
    now = time.time()
    try:
        header = jwt.get_unverified_header(token)
        kid = header.get("kid")
    except Exception:
        kid = None
    try:
        jwks = _JWKS_CACHE.get(jwks_url)
        fetched_at = float(_JWKS_FETCHED_AT.get(jwks_url) or 0.0)
        if not jwks or (now - fetched_at) >= float(_JWKS_CACHE_TTL):
            resp = _req.get(jwks_url, timeout=5)
            resp.raise_for_status()
            jwks = resp.json()
            _JWKS_CACHE[jwks_url] = jwks
            _JWKS_FETCHED_AT[jwks_url] = now
        keys = jwks.get("keys") if isinstance(jwks, dict) else []
        selected = None
        if isinstance(keys, list):
            if kid:
                selected = next((k for k in keys if isinstance(k, dict) and k.get("kid") == kid), None)
            if selected is None and keys:
                selected = keys[0] if isinstance(keys[0], dict) else None
        if not isinstance(selected, dict):
            return None
        jwk = jwt.PyJWK.from_dict(selected).key
        alg = selected.get("alg")
        algs = [alg] if isinstance(alg, str) and alg else ["RS256", "ES256"]
        decode_kwargs = {
            "key": jwk,
            "algorithms": algs,
            "options": {"verify_signature": True, "verify_aud": bool(audience), "verify_iss": bool(issuer)},
        }
        if audience:
            decode_kwargs["audience"] = audience
        if issuer:
            decode_kwargs["issuer"] = issuer
        claims = jwt.decode(token, **decode_kwargs)
        role = claims.get(role_claim)
        if isinstance(role, list):
            role = role[0] if role else None
        return str(role) if role else None
    except Exception:
        # Force one cache refresh attempt to tolerate key rotation
        try:
            resp = _req.get(jwks_url, timeout=5)
            resp.raise_for_status()
            jwks = resp.json()
            _JWKS_CACHE[jwks_url] = jwks
            _JWKS_FETCHED_AT[jwks_url] = time.time()
            keys = jwks.get("keys") if isinstance(jwks, dict) else []
            selected = None
            if isinstance(keys, list):
                if kid:
                    selected = next((k for k in keys if isinstance(k, dict) and k.get("kid") == kid), None)
                if selected is None and keys:
                    selected = keys[0] if isinstance(keys[0], dict) else None
            if not isinstance(selected, dict):
                return None
            jwk = jwt.PyJWK.from_dict(selected).key
            alg = selected.get("alg")
            algs = [alg] if isinstance(alg, str) and alg else ["RS256", "ES256"]
            decode_kwargs = {
                "key": jwk,
                "algorithms": algs,
                "options": {"verify_signature": True, "verify_aud": bool(audience), "verify_iss": bool(issuer)},
            }
            if audience:
                decode_kwargs["audience"] = audience
            if issuer:
                decode_kwargs["issuer"] = issuer
            claims = jwt.decode(token, **decode_kwargs)
            role = claims.get(role_claim)
            if isinstance(role, list):
                role = role[0] if role else None
            return str(role) if role else None
        except Exception:
            return None


def _introspect_token(auth_header: Optional[str]) -> Optional[dict]:
    """Use OAuth2 token introspection endpoint to validate bearer tokens and extract claims.

    Environment variables:
      - OIDC_INTROSPECTION_URL: token introspection endpoint (required to enable)
      - OIDC_INTROSPECTION_CLIENT_ID / _CLIENT_SECRET: optional client creds for basic auth
      - OIDC_ROLE_CLAIM: claim name carrying role (default: 'role')
    Returns a dict of claims on success or None on failure.
    """
    try:
        import requests as _req
    except Exception:
        return None
    if not auth_header or not auth_header.lower().startswith("bearer "):
        return None
    token = auth_header.split(" ", 1)[1].strip()
    introspect_url = os.getenv("OIDC_INTROSPECTION_URL")
    if not introspect_url:
        return None
    # Simple in-memory cache keyed by token (short TTL)
    try:
        now = time.time()
    except Exception:
        import time as time
        now = time.time()
    cached = _INTROSPECTION_CACHE.get(token)
    if cached:
        ts, data = cached
        try:
            if now - float(ts) < float(_INTROSPECTION_TTL):
                return data
        except Exception:
            pass
    try:
        auth = None
        client_id = os.getenv("OIDC_INTROSPECTION_CLIENT_ID")
        client_secret = os.getenv("OIDC_INTROSPECTION_CLIENT_SECRET")
        if client_id and client_secret:
            auth = (client_id, client_secret)
        resp = _req.post(introspect_url, data={"token": token}, auth=auth, timeout=5)
        resp.raise_for_status()
        data = resp.json()
        # Standard introspection includes 'active' boolean
        if not data.get("active"):
            return None
        # Cache response
        try:
            _INTROSPECTION_CACHE[token] = (now, data)
        except Exception:
            pass
        return data
    except Exception:
        return None

def require_role_or_oidc(allowed_roles: Iterable[str]) -> Callable[[Optional[str], Optional[str]], str]:
    allowed = set(allowed_roles)

    # lazy import to avoid cycles
    try:
        from src.app.observability.iam_events import emit_iam_activity as _emit_iam
    except Exception:
        _emit_iam = None  # type: ignore

    def _dep(
        x_api_key: Optional[str] = Header(default=None, alias="x-api-key"),
        authorization: Optional[str] = Header(default=None, alias="Authorization"),
        request: Request = None,  # FastAPI injects Request
    ) -> str:
        source_ip = request.client.host if request and request.client else "unknown"
        locked, _remaining = _is_ip_locked_out(source_ip)
        if locked:
            raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="auth_ip_locked_out")
        effective_key = x_api_key
        try:
            if not effective_key and request is not None:
                effective_key = request.cookies.get("shopsquire_api_key")
        except Exception:
            effective_key = x_api_key
        # Prefer API key; otherwise try OIDC JWT
        role = get_role_from_key(effective_key)
        if role and _admin_oidc_required() and _is_admin_operator_scope(allowed) and role in (ROLE_OWNER, ROLE_DEVELOPER):
            # In hardened mode, owner/developer accesses require bearer/OIDC.
            role = None
        if not role:
            # Prefer JWT claim verification, then token introspection if configured
            role = _verify_oidc_jwt(authorization)
        if not role:
            try:
                data = _introspect_token(authorization)
                if isinstance(data, dict):
                    role_claim = os.getenv("OIDC_ROLE_CLAIM", "role")
                    r = data.get(role_claim) or data.get("roles") or data.get("scope")
                    if isinstance(r, list):
                        role = str(r[0]) if r else None
                    elif isinstance(r, str) and " " in r:
                        # scope string: pick first role-like token
                        role = r.split(" ")[0]
                    else:
                        role = str(r) if r else None
            except Exception:
                pass
        # Backwards-compatible tolerant behavior for local/dev merchant key
        try:
            if not role and effective_key and effective_key == _role_keys().get(ROLE_MERCHANT):
                role = ROLE_MERCHANT
        except Exception:
            pass
        if not role:
            _record_failed_auth(source_ip)
            try:
                if _emit_iam:
                    _emit_iam(
                        action="authn_check",
                        outcome="missing",
                        subject={"actor_id": (effective_key or "bearer"), "role": None},
                        resource={"path": getattr(request, "url", getattr(request, "scope", {})).path if request else "", "method": getattr(request, "method", "")},
                        risk="medium",
                        tags=["authn", "oidc" if authorization else "api_key"],
                        correlation_id=(request.headers.get("X-Correlation-ID") if request else None),
                    )
            except Exception:
                pass
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or missing credentials")
        if not _assert_privileged_role_server_side(role=role, authorization=authorization, effective_key=effective_key):
            _record_failed_auth(source_ip)
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="privileged_role_server_assertion_failed")
        if role not in allowed:
            try:
                if effective_key and effective_key == _role_keys().get(ROLE_MERCHANT) and ROLE_MERCHANT in allowed:
                    return ROLE_MERCHANT
            except Exception:
                pass
            try:
                if _emit_iam:
                    _emit_iam(
                        action="authz_check",
                        outcome="denied",
                        subject={"actor_id": (effective_key or "bearer"), "role": role},
                        resource={"path": getattr(request, "url", getattr(request, "scope", {})).path if request else "", "method": getattr(request, "method", ""), "target_role": list(allowed)},
                        risk="medium",
                        tags=["authz"],
                        correlation_id=(request.headers.get("X-Correlation-ID") if request else None),
                    )
            except Exception:
                pass
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role")
        if _abac_enabled():
            allow, reason, ctx = _evaluate_abac(role=role, request=request)
            if not allow:
                try:
                    _emit_abac_deny_trace(request, role, str(reason or "abac_denied"), ctx if isinstance(ctx, dict) else {})
                except Exception:
                    pass
                try:
                    if _emit_iam:
                        _emit_iam(
                            action="authz_check",
                            outcome="denied",
                            subject={"actor_id": (effective_key or "bearer"), "role": role, "tenant_id": (ctx or {}).get("tenant_id")},
                            resource=(ctx or {}).get("resource") or {"path": getattr(request, "url", getattr(request, "scope", {})).path if request else "", "method": getattr(request, "method", "")},
                            risk="high" if ((ctx or {}).get("resource") or {}).get("sensitivity") == "high" else "medium",
                            tags=["authz", "abac"],
                            correlation_id=(request.headers.get("X-Correlation-ID") if request else None),
                        )
                except Exception:
                    pass
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"ABAC deny: {reason}")
        _authorize_operator_tenant(
            request=request,
            role=role,
            effective_key=effective_key,
            authorization=authorization,
        )
        try:
            if _emit_iam:
                _emit_iam(
                    action="access_granted",
                    outcome="granted",
                    subject={"actor_id": (effective_key or "bearer"), "role": role},
                    resource={"path": getattr(request, "url", getattr(request, "scope", {})).path if request else "", "method": getattr(request, "method", ""), "target_role": list(allowed)},
                    risk="low",
                    tags=["authz"],
                    correlation_id=(request.headers.get("X-Correlation-ID") if request else None),
                )
        except Exception:
            pass

        # IT-PREV-05 / IT-DET-01 — Admin IP allowlist + off-hours detection.
        _privileged_roles = {ROLE_OWNER, ROLE_DEVELOPER, "admin"}
        if role in _privileged_roles:
            _allowlist_raw = str(os.getenv("ADMIN_IP_ALLOWLIST", "") or "").strip()
            if _allowlist_raw:
                _allowed_ips = {ip.strip() for ip in _allowlist_raw.split(",") if ip.strip()}
                if source_ip not in _allowed_ips:
                    try:
                        from src.app.security.insider_threat_detector import InsiderThreatSignal, _emit as _it_emit
                        _it_emit(InsiderThreatSignal(
                            signal_type="admin_access_from_unlisted_ip",
                            actor=effective_key or "unknown",
                            resource=getattr(request.url, "path", "unknown") if request else "unknown",
                            severity="critical",
                            context={"role": role, "source_ip": source_ip, "allowlist_size": len(_allowed_ips)},
                        ))
                    except Exception:
                        pass
                    _record_failed_auth(source_ip)
                    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="admin_ip_not_in_allowlist")
            try:
                from src.app.security.insider_threat_detector import detect_off_hours_admin
                detect_off_hours_admin(
                    actor=effective_key or "unknown",
                    action=getattr(request.url, "path", "unknown") if request else "unknown",
                    ip=source_ip,
                    role=role,
                )
            except Exception:
                pass

        _clear_failed_auth(source_ip)
        return role

    return _dep


ROLE_MERCHANT = "merchant"
ROLE_OWNER = "owner"
ROLE_DEVELOPER = "developer"


def _non_dev_env() -> bool:
    """Non-dev = staging/prod/anything that isn't a local/dev/test run (mirrors config._is_non_dev_env)."""
    return str(os.getenv("APP_ENV", "local") or "local").strip().lower() not in (
        "local", "dev", "development", "test", "testing",
    )


def _env_role_key(name: str, dev_default: str) -> str:
    """Resolve a role's env key with a FAIL-CLOSED default in non-dev.

    Dev/local/test: an unset key falls back to the well-known 'local-*' value (ergonomics). In a non-dev
    env an UNSET key resolves to "" instead of the guessable default — get_role_from_key() skips empty
    keys, so a forgotten key config is fail-CLOSED (no backdoor), while an explicitly-set env key and any
    vault/file keys still authenticate. Closes the "auth defaults to a known key" fail-open."""
    v = os.getenv(name)
    if v not in (None, ""):
        return str(v)
    return "" if _non_dev_env() else dev_default


def _role_keys() -> dict[str, str]:
    return {
        ROLE_MERCHANT: _env_role_key("MERCHANT_API_KEY", "local-merchant-key"),
        ROLE_OWNER: _env_role_key("OWNER_API_KEY", "local-owner-key"),
        ROLE_DEVELOPER: _env_role_key("DEVELOPER_API_KEY", "local-developer-key"),
    }


def _keys_path() -> Path:
    return Path(os.getenv("API_KEYS_PATH", "config/api_keys.json"))


def _load_file_keys() -> dict[str, list[str]]:
    # Prefer secrets manager when available; otherwise fallback to local file
    out: dict[str, list[str]] = {}
    try:
        from src.app.security.secrets_store import fetch_api_keys

        vault_keys = fetch_api_keys() or {}
        for role, recs in (vault_keys or {}).items():
            if isinstance(recs, list):
                out[role] = [str(r.get("key")) for r in recs if r and isinstance(r, dict) and r.get("key")]
    except Exception:
        # ignore vault errors and fall through to file
        pass

    path = _keys_path()
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                for role, keys in data.items():
                    if isinstance(keys, list):
                        file_keys = [str(k.get("key")) if isinstance(k, dict) and k.get("key") else str(k) for k in keys]
                        if role in out:
                            # merge unique
                            existing = set(out.get(role) or [])
                            for fk in file_keys:
                                if fk and fk not in existing:
                                    out[role].append(fk)
                        else:
                            out[role] = [k for k in file_keys if k]
        except Exception:
            pass
    return out


def get_role_from_key(key: Optional[str]) -> Optional[str]:
    if not key:
        return None
    key = key.strip()
    file_keys = _load_file_keys()
    for role, role_key in _role_keys().items():
        if role_key and key == role_key:
            return role
        if key in file_keys.get(role, []):
            return role
    return None


def require_role(allowed_roles: Iterable[str]):
    allowed = set(allowed_roles)

    try:
        from src.app.observability.iam_events import emit_iam_activity as _emit_iam
    except Exception:
        _emit_iam = None  # type: ignore

    def _dep(
        x_api_key: Optional[str] = Header(default=None, alias="x-api-key"),
        authorization: Optional[str] = Header(default=None, alias="Authorization"),
        request: Request = None,
    ) -> str:
        source_ip = request.client.host if request and request.client else "unknown"
        locked, _remaining = _is_ip_locked_out(source_ip)
        if locked:
            raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="auth_ip_locked_out")
        effective_key = x_api_key
        try:
            if not effective_key and request is not None:
                effective_key = request.cookies.get("shopsquire_api_key")
        except Exception:
            effective_key = x_api_key
        role = get_role_from_key(effective_key)
        if role and _admin_oidc_required() and _is_admin_operator_scope(allowed) and role in (ROLE_OWNER, ROLE_DEVELOPER):
            role = None
        if not role and authorization:
            try:
                role = get_role_from_bearer(authorization)
            except Exception:
                role = None
        # Backwards-compatible tolerant behavior for local/dev keys used in tests
        try:
            if not role and effective_key and effective_key == _role_keys().get(ROLE_MERCHANT):
                role = ROLE_MERCHANT
        except Exception:
            pass
        if not role:
            _record_failed_auth(source_ip)
            try:
                if _emit_iam:
                    _emit_iam(
                        action="authn_check",
                        outcome="invalid",
                        subject={"actor_id": (effective_key or "api_key"), "role": None},
                        resource={"path": getattr(request, "url", getattr(request, "scope", {})).path if request else "", "method": getattr(request, "method", "")},
                        risk="medium",
                        tags=["authn", "api_key"],
                        correlation_id=(request.headers.get("X-Correlation-ID") if request else None),
                    )
            except Exception:
                pass
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or missing API key")
        if not _assert_privileged_role_server_side(role=role, authorization=authorization, effective_key=effective_key):
            _record_failed_auth(source_ip)
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="privileged_role_server_assertion_failed")
        if role not in allowed:
            # If the provided key equals the configured merchant key and merchant role is allowed,
            # accept it to support test environments using the default local key.
            try:
                if effective_key and effective_key == _role_keys().get(ROLE_MERCHANT) and ROLE_MERCHANT in allowed:
                    return ROLE_MERCHANT
            except Exception:
                pass
            try:
                if _emit_iam:
                    _emit_iam(
                        action="authz_check",
                        outcome="denied",
                        subject={"actor_id": (effective_key or "api_key"), "role": role},
                        resource={"path": getattr(request, "url", getattr(request, "scope", {})).path if request else "", "method": getattr(request, "method", ""), "target_role": list(allowed)},
                        risk="medium",
                        tags=["authz"],
                        correlation_id=(request.headers.get("X-Correlation-ID") if request else None),
                    )
            except Exception:
                pass
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role")
        if _abac_enabled():
            allow, reason, ctx = _evaluate_abac(role=role, request=request)
            if not allow:
                try:
                    _emit_abac_deny_trace(request, role, str(reason or "abac_denied"), ctx if isinstance(ctx, dict) else {})
                except Exception:
                    pass
                try:
                    if _emit_iam:
                        _emit_iam(
                            action="authz_check",
                            outcome="denied",
                            subject={"actor_id": (effective_key or "api_key"), "role": role, "tenant_id": (ctx or {}).get("tenant_id")},
                            resource=(ctx or {}).get("resource") or {"path": getattr(request, "url", getattr(request, "scope", {})).path if request else "", "method": getattr(request, "method", "")},
                            risk="high" if ((ctx or {}).get("resource") or {}).get("sensitivity") == "high" else "medium",
                            tags=["authz", "abac"],
                            correlation_id=(request.headers.get("X-Correlation-ID") if request else None),
                        )
                except Exception:
                    pass
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"ABAC deny: {reason}")
        _authorize_operator_tenant(
            request=request,
            role=role,
            effective_key=effective_key,
            authorization=authorization,
        )
        try:
            if _emit_iam:
                _emit_iam(
                    action="access_granted",
                    outcome="granted",
                    subject={"actor_id": (effective_key or "api_key"), "role": role},
                    resource={"path": getattr(request, "url", getattr(request, "scope", {})).path if request else "", "method": getattr(request, "method", ""), "target_role": list(allowed)},
                    risk="low",
                    tags=["authz"],
                    correlation_id=(request.headers.get("X-Correlation-ID") if request else None),
                )
        except Exception:
            pass

        # IT-PREV-05 / IT-DET-01 — Admin IP allowlist + off-hours detection.
        _privileged_roles = {ROLE_OWNER, ROLE_DEVELOPER, "admin"}
        if role in _privileged_roles:
            _allowlist_raw = str(os.getenv("ADMIN_IP_ALLOWLIST", "") or "").strip()
            if _allowlist_raw:
                _allowed_ips = {ip.strip() for ip in _allowlist_raw.split(",") if ip.strip()}
                if source_ip not in _allowed_ips:
                    try:
                        from src.app.security.insider_threat_detector import InsiderThreatSignal, _emit as _it_emit
                        _it_emit(InsiderThreatSignal(
                            signal_type="admin_access_from_unlisted_ip",
                            actor=effective_key or "unknown",
                            resource=getattr(request.url, "path", "unknown") if request else "unknown",
                            severity="critical",
                            context={"role": role, "source_ip": source_ip, "allowlist_size": len(_allowed_ips)},
                        ))
                    except Exception:
                        pass
                    _record_failed_auth(source_ip)
                    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="admin_ip_not_in_allowlist")
            try:
                from src.app.security.insider_threat_detector import detect_off_hours_admin
                detect_off_hours_admin(
                    actor=effective_key or "unknown",
                    action=getattr(request.url, "path", "unknown") if request else "unknown",
                    ip=source_ip,
                    role=role,
                )
            except Exception:
                pass

        _clear_failed_auth(source_ip)
        return role

    return _dep


def get_current_role(
    x_api_key: Optional[str] = Header(default=None, alias="x-api-key"),
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
) -> str:
    role = get_role_from_key(x_api_key)
    if not role and authorization:
        role = get_role_from_bearer(authorization)
    if role and _admin_oidc_required() and role in (ROLE_OWNER, ROLE_DEVELOPER) and not authorization:
        role = None
    if not role:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or missing credentials")
    return role


def get_role_from_bearer(auth_header: Optional[str]) -> Optional[str]:
    """Helper to derive role from a bearer Authorization header using JWT claims or token introspection."""
    try:
        role = _verify_local_jwt(auth_header)
        if role:
            return role
    except Exception:
        pass
    try:
        role = _verify_oidc_jwt(auth_header)
        if role:
            return role
    except Exception:
        pass
    try:
        data = _introspect_token(auth_header)
        if isinstance(data, dict):
            # Optional scope requirement
            required_scope = os.getenv("OIDC_REQUIRED_SCOPE")
            if required_scope:
                scopes = data.get("scope") or data.get("scp") or ""
                if isinstance(scopes, list):
                    if required_scope not in scopes:
                        return None
                elif isinstance(scopes, str):
                    if required_scope not in scopes.split():
                        return None
            role_claim = os.getenv("OIDC_ROLE_CLAIM", "role")
            r = data.get(role_claim) or data.get("roles") or data.get("scope")
            if isinstance(r, list):
                return str(r[0]) if r else None
            if isinstance(r, str) and " " in r:
                return r.split(" ")[0]
            return str(r) if r else None
    except Exception:
        pass
    return None
