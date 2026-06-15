from __future__ import annotations

import hashlib
import os
import secrets
import time
import base64
import hmac
import json

import jwt as pyjwt
from datetime import datetime, timedelta
from typing import Dict
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Request, Response, Cookie
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, EmailStr
from sqlalchemy import text as sql_text

from src.app.models.db import db_session
from src.app.policy.action_authority_matrix import AuthDecision, evaluate as evaluate_action_authority
from src.app.security.csrf_middleware import generate_csrf_token, set_csrf_cookie
from src.app.security.iam import log_iam_event, check_bruteforce, check_impossible_travel, emit_iam_anomaly
from src.app.observability.tracing import get_tracer
from src.app.services.pii_crypto import encrypt_pii, pii_hash
import httpx


router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

# ── Argon2id support (OWASP-recommended for new passwords) ──────────────────
# Falls back to PBKDF2-HMAC-SHA256 when argon2-cffi is not installed.
# Existing PBKDF2 hashes are detected by absence of the "$argon2" prefix and
# verified against legacy iterations; successful login triggers a lazy upgrade.
try:
    from argon2 import PasswordHasher as _Argon2PH
    from argon2.exceptions import VerifyMismatchError as _ArgonMismatch, InvalidHashError as _ArgonInvalid
    _ARGON2_PH: "_Argon2PH | None" = _Argon2PH(
        time_cost=int(os.getenv("ARGON2_TIME_COST", "3")),
        memory_cost=int(os.getenv("ARGON2_MEMORY_COST_KB", "65536")),
        parallelism=int(os.getenv("ARGON2_PARALLELISM", "4")),
        hash_len=32,
        salt_len=16,
    )
    _ARGON2_AVAILABLE = True
except ImportError:
    _ARGON2_PH = None
    _ARGON2_AVAILABLE = False
    _ArgonMismatch = Exception  # type: ignore[misc,assignment]
    _ArgonInvalid = Exception  # type: ignore[misc,assignment]
tracer = get_tracer("auth-router")

SESSION_COOKIE_NAME = "shopsquire_session"
API_KEY_COOKIE_NAME = "shopsquire_api_key"


def _is_https_request(request: Request | None) -> bool:
    try:
        if request is None:
            return False
        proto = str(request.headers.get("x-forwarded-proto") or "").lower()
        if proto:
            return proto == "https"
        return str(request.url.scheme).lower() == "https"
    except Exception:
        return False


def _set_session_cookie(resp: Response, token: str, request: Request | None) -> None:
    try:
        secure = _is_https_request(request)
        resp.set_cookie(
            key=SESSION_COOKIE_NAME,
            value=str(token or ""),
            httponly=True,
            secure=secure,
            samesite="strict",
            max_age=7 * 24 * 60 * 60,
            path="/",
        )
    except Exception:
        pass


def _clear_session_cookie(resp: Response) -> None:
    try:
        resp.delete_cookie(SESSION_COOKIE_NAME, path="/")
    except Exception:
        pass


def _set_api_key_cookie(resp: Response, key: str, request: Request | None) -> None:
    try:
        secure = _is_https_request(request)
        resp.set_cookie(
            key=API_KEY_COOKIE_NAME,
            value=str(key or ""),
            httponly=True,
            secure=secure,
            samesite="strict",
            max_age=24 * 60 * 60,
            path="/",
        )
    except Exception:
        pass


def _clear_api_key_cookie(resp: Response) -> None:
    try:
        resp.delete_cookie(API_KEY_COOKIE_NAME, path="/")
    except Exception:
        pass


def _ensure_auth_tables():
    # Alembic is the source of truth for non-SQLite DBs.
    non_sqlite = False
    try:
        from src.app.models.db import get_engine

        eng = get_engine()
        non_sqlite = bool(getattr(eng, "dialect", None) is not None and eng.dialect.name != "sqlite")
    except Exception:
        pass

    if non_sqlite:
        # Keep non-SQLite schemas migration-first, but ensure refresh token
        # table exists for auth token rotation compatibility.
        with db_session() as db:
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS refresh_tokens (
                  id TEXT PRIMARY KEY,
                  user_id TEXT NOT NULL,
                  token_hash TEXT UNIQUE NOT NULL,
                  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                  expires_at TEXT,
                  revoked_at TEXT,
                  rotated_from TEXT
                )
                """
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS security_forced_reauth_flags (
                  id TEXT PRIMARY KEY,
                  target_type TEXT NOT NULL,
                  target_value TEXT NOT NULL,
                  reason TEXT,
                  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                  UNIQUE(target_type, target_value)
                )
                """
            )
            db.commit()
        return

    with db_session() as db:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS user_accounts (
              id TEXT PRIMARY KEY,
              email TEXT UNIQUE NOT NULL,
              name TEXT,
              password_hash TEXT NOT NULL,
              salt TEXT NOT NULL,
              created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS session_tokens (
              id TEXT PRIMARY KEY,
              user_id TEXT NOT NULL,
              token TEXT UNIQUE NOT NULL,
              token_hash TEXT,
              created_at TEXT DEFAULT CURRENT_TIMESTAMP,
              expires_at TEXT
            )
            """
        )
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS refresh_tokens (
              id TEXT PRIMARY KEY,
              user_id TEXT NOT NULL,
              token_hash TEXT UNIQUE NOT NULL,
              created_at TEXT DEFAULT CURRENT_TIMESTAMP,
              expires_at TEXT,
              revoked_at TEXT,
              rotated_from TEXT
            )
            """
        )
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS payment_methods (
              id TEXT PRIMARY KEY,
              user_id TEXT NOT NULL,
              label TEXT,
              brand TEXT,
              last4 TEXT,
              created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS oauth_identities (
              id TEXT PRIMARY KEY,
              provider TEXT NOT NULL,
              provider_user_id TEXT NOT NULL,
              user_id TEXT NOT NULL,
              email TEXT,
              created_at TEXT DEFAULT CURRENT_TIMESTAMP,
              UNIQUE(provider, provider_user_id)
            )
            """
        )
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS oauth_states (
              state TEXT PRIMARY KEY,
              return_to TEXT,
              expires_at TEXT,
              code_verifier TEXT,
              nonce TEXT,
              created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS security_forced_reauth_flags (
              id TEXT PRIMARY KEY,
              target_type TEXT NOT NULL,
              target_value TEXT NOT NULL,
              reason TEXT,
              created_at TEXT DEFAULT CURRENT_TIMESTAMP,
              UNIQUE(target_type, target_value)
            )
            """
        )
        # Backward-compatible schema updates
        try:
            db.execute(sql_text("ALTER TABLE session_tokens ADD COLUMN token_hash TEXT"))
        except Exception:
            pass
        try:
            db.execute(sql_text("ALTER TABLE oauth_states ADD COLUMN code_verifier TEXT"))
        except Exception:
            pass
        try:
            db.execute(sql_text("ALTER TABLE oauth_states ADD COLUMN nonce TEXT"))
        except Exception:
            pass
        db.commit()


def _is_forced_reauth(user_id: str | None = None, email: str | None = None) -> bool:
    uid = str(user_id or "").strip()
    em = str(email or "").strip().lower()
    if not uid and not em:
        return False
    try:
        with db_session() as db:
            if uid:
                row = db.execute(
                    "SELECT 1 FROM security_forced_reauth_flags WHERE target_type = 'user_id' AND target_value = :v LIMIT 1",
                    {"v": uid},
                ).fetchone()
                if row:
                    return True
            if em:
                row = db.execute(
                    "SELECT 1 FROM security_forced_reauth_flags WHERE target_type = 'email' AND lower(target_value) = :v LIMIT 1",
                    {"v": em},
                ).fetchone()
                if row:
                    return True
    except Exception:
        return False
    return False


def _clear_forced_reauth(user_id: str | None = None, email: str | None = None) -> None:
    uid = str(user_id or "").strip()
    em = str(email or "").strip().lower()
    if not uid and not em:
        return
    try:
        with db_session() as db:
            if uid:
                db.execute(
                    "DELETE FROM security_forced_reauth_flags WHERE target_type = 'user_id' AND target_value = :v",
                    {"v": uid},
                )
            if em:
                db.execute(
                    "DELETE FROM security_forced_reauth_flags WHERE target_type = 'email' AND lower(target_value) = :v",
                    {"v": em},
                )
            db.commit()
    except Exception:
        pass


def _hash_password(password: str, salt: str) -> str:
    """Hash a new password for storage.  Uses argon2id when available (salt embedded
    in the returned hash string); falls back to PBKDF2-HMAC-SHA256 600k iterations."""
    if _ARGON2_AVAILABLE and _ARGON2_PH is not None:
        return _ARGON2_PH.hash(password)  # salt is embedded; `salt` param ignored
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), 600_000
    ).hex()


def _verify_password(password: str, stored_hash: str, salt: str) -> tuple[bool, str | None]:
    """Verify *password* against *stored_hash*.

    Returns ``(is_valid, upgraded_hash_or_None)``.  When ``upgraded_hash_or_None``
    is not None the caller should persist it so the account migrates to argon2id.
    Supports three hash formats (detected automatically):
      1. ``$argon2id$…`` — argon2id (current default)
      2. 64-char hex     — PBKDF2-HMAC-SHA256 with 100 000 iterations (legacy)
      3. anything else   — treated as PBKDF2 100k (safest fallback)
    """
    if stored_hash.startswith("$argon2"):
        if not _ARGON2_AVAILABLE or _ARGON2_PH is None:
            return False, None
        try:
            _ARGON2_PH.verify(stored_hash, password)
            new_hash = _ARGON2_PH.hash(password) if _ARGON2_PH.check_needs_rehash(stored_hash) else None
            return True, new_hash
        except (_ArgonMismatch, _ArgonInvalid, Exception):  # type: ignore[misc]
            return False, None
    # Legacy PBKDF2-HMAC-SHA256 path — always 100 000 iterations (historical value)
    try:
        expected = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt.encode("utf-8"), 100_000
        ).hex()
        if hmac.compare_digest(expected, stored_hash):
            upgraded = _ARGON2_PH.hash(password) if (_ARGON2_AVAILABLE and _ARGON2_PH is not None) else None
            return True, upgraded
    except Exception:
        pass
    return False, None


def _jwt_secret() -> str:
    return str(os.getenv("JWT_SIGNING_KEY", "") or "").strip()


def _jwt_issuer() -> str:
    return str(os.getenv("JWT_ISSUER", "shopsquire") or "shopsquire")


def _jwt_audience() -> str:
    return str(os.getenv("JWT_AUDIENCE", "shopsquire-api") or "shopsquire-api")


def _jwt_default_role() -> str:
    return str(os.getenv("LOCAL_AUTH_DEFAULT_ROLE", "merchant") or "merchant")


def _jwt_encode_hs256(claims: Dict[str, object], secret: str) -> str:
    """Encode JWT claims using PyJWT (HS256)."""
    return pyjwt.encode(dict(claims), secret, algorithm="HS256")


def _jwt_decode_hs256(token: str, secret: str, *, issuer: str, audience: str) -> Dict | None:
    """Decode and validate a JWT using PyJWT (HS256 only)."""
    try:
        return pyjwt.decode(
            str(token or ""),
            secret,
            algorithms=["HS256"],
            issuer=issuer,
            audience=audience,
            options={"require": ["exp", "iat", "iss", "aud", "sub"]},
        )
    except (pyjwt.InvalidTokenError, pyjwt.ExpiredSignatureError, Exception):
        return None


def _issue_access_jwt(*, user_id: str, email: str | None, role: str) -> Dict:
    secret = _jwt_secret()
    if not secret:
        return {"token": "", "expires_in": 0}
    ttl = int(os.getenv("JWT_ACCESS_TTL_SECONDS", "900") or 900)
    now = int(time.time())
    exp = now + max(60, ttl)
    claims = {
        "sub": str(user_id),
        "email": str(email or ""),
        "role": str(role or _jwt_default_role()),
        "typ": "access",
        "iss": _jwt_issuer(),
        "aud": _jwt_audience(),
        "iat": now,
        "exp": exp,
        "jti": secrets.token_hex(8),
    }
    token = _jwt_encode_hs256(claims, secret)
    return {"token": str(token), "expires_in": int(max(1, exp - now))}


def _issue_refresh_jwt(*, user_id: str, email: str | None, role: str, rotated_from: str | None = None) -> Dict:
    secret = _jwt_secret()
    if not secret:
        return {"token": "", "expires_in": 0}
    ttl = int(os.getenv("JWT_REFRESH_TTL_SECONDS", "86400") or 86400)
    now = int(time.time())
    exp = now + max(300, ttl)
    jti = secrets.token_hex(16)
    claims = {
        "sub": str(user_id),
        "email": str(email or ""),
        "role": str(role or _jwt_default_role()),
        "typ": "refresh",
        "iss": _jwt_issuer(),
        "aud": _jwt_audience(),
        "iat": now,
        "exp": exp,
        "jti": jti,
    }
    token = str(_jwt_encode_hs256(claims, secret))
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    expires_at = datetime.utcfromtimestamp(exp).isoformat()
    with db_session() as db:
        db.execute(
            """
            INSERT INTO refresh_tokens (id, user_id, token_hash, expires_at, rotated_from)
            VALUES (:id, :user_id, :token_hash, :expires_at, :rotated_from)
            """,
            {
                "id": f"rt-{jti}",
                "user_id": str(user_id),
                "token_hash": token_hash,
                "expires_at": expires_at,
                "rotated_from": rotated_from,
            },
        )
        db.commit()
    return {"token": token, "expires_in": int(max(1, exp - now))}


def _issue_jwt_pair(*, user_id: str, email: str | None, role: str) -> Dict[str, object]:
    access = _issue_access_jwt(user_id=user_id, email=email, role=role)
    refresh = _issue_refresh_jwt(user_id=user_id, email=email, role=role)
    if not access.get("token") or not refresh.get("token"):
        return {"access_token": None, "access_expires_in": 0, "refresh_token": None, "refresh_expires_in": 0}
    return {
        "access_token": access["token"],
        "access_expires_in": access["expires_in"],
        "refresh_token": refresh["token"],
        "refresh_expires_in": refresh["expires_in"],
    }


def _decode_refresh_jwt(token: str) -> Dict | None:
    secret = _jwt_secret()
    if not secret:
        return None
    claims = _jwt_decode_hs256(str(token or ""), secret, issuer=_jwt_issuer(), audience=_jwt_audience())
    if not claims:
        return None
    if str(claims.get("typ") or "").lower() != "refresh":
        return None
    return claims


def _revoke_refresh_token(token: str) -> bool:
    token_hash = hashlib.sha256(str(token or "").encode("utf-8")).hexdigest()
    with db_session() as db:
        row = db.execute(
            "SELECT id, revoked_at, expires_at FROM refresh_tokens WHERE token_hash = :h LIMIT 1",
            {"h": token_hash},
        ).fetchone()
        if not row:
            return False
        if row[1]:
            return False
        try:
            exp = row[2]
            if exp and datetime.utcnow() > datetime.fromisoformat(str(exp)):
                return False
        except Exception:
            pass
        db.execute(
            "UPDATE refresh_tokens SET revoked_at = CURRENT_TIMESTAMP WHERE token_hash = :h",
            {"h": token_hash},
        )
        db.commit()
    return True


def _rotate_refresh_token(token: str) -> Dict | None:
    claims = _decode_refresh_jwt(token)
    if not claims:
        return None
    if not _revoke_refresh_token(token):
        return None
    return _issue_refresh_jwt(
        user_id=str(claims.get("sub") or ""),
        email=str(claims.get("email") or ""),
        role=str(claims.get("role") or _jwt_default_role()),
        rotated_from=str(claims.get("jti") or ""),
    )


def _issue_token(user_id: str) -> Dict:
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    expires_at = (datetime.utcnow() + timedelta(days=7)).isoformat()
    with db_session() as db:
        # Store only token_hash; keep token column null for backward compat and plan removal
        try:
            db.execute(
                "INSERT INTO session_tokens (id, user_id, token_hash, expires_at) VALUES (:id, :user_id, :token_hash, :expires_at)",
                {"id": secrets.token_hex(16), "user_id": user_id, "token_hash": token_hash, "expires_at": expires_at},
            )
        except Exception:
            # Backward-compatibility for older schemas where `token` is required.
            db.execute(
                "INSERT INTO session_tokens (id, user_id, token, token_hash, expires_at) VALUES (:id, :user_id, :token, :token_hash, :expires_at)",
                {"id": secrets.token_hex(16), "user_id": user_id, "token": token, "token_hash": token_hash, "expires_at": expires_at},
            )
        db.commit()
    return {"token": token, "expires_at": expires_at}


def _user_from_token(token: str):
    if not token:
        return None
    with db_session() as db:
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        row = db.execute(
            "SELECT u.id, u.email, u.name, s.expires_at FROM session_tokens s JOIN user_accounts u ON u.id = s.user_id WHERE s.token_hash = :th",
            {"th": token_hash},
        ).fetchone()
        if not row:
            row = db.execute(
                "SELECT u.id, u.email, u.name, s.expires_at FROM session_tokens s JOIN user_accounts u ON u.id = s.user_id WHERE s.token = :t",
                {"t": token},
            ).fetchone()
        if not row:
            return None
        try:
            expires_at = row[3]
            if expires_at and datetime.utcnow() > datetime.fromisoformat(str(expires_at)):
                # Attempt delete by hash first, then token
                try:
                    db.execute(sql_text("DELETE FROM session_tokens WHERE token_hash = :th"), {"th": token_hash})
                except Exception:
                    db.execute(sql_text("DELETE FROM session_tokens WHERE token = :t"), {"t": token})
                db.commit()
                return None
        except Exception:
            pass
        # Enforce post-incident forced reauth: session token is no longer valid
        # until login completes step-up flow.
        try:
            user_id = row[0]
            user_email = row[1]
            if _is_forced_reauth(user_id=str(user_id or ""), email=str(user_email or "")):
                try:
                    db.execute(sql_text("DELETE FROM session_tokens WHERE user_id = :uid"), {"uid": str(user_id)})
                except Exception:
                    pass
                try:
                    db.execute(sql_text("UPDATE refresh_tokens SET revoked_at = CURRENT_TIMESTAMP WHERE user_id = :uid AND revoked_at IS NULL"), {"uid": str(user_id)})
                except Exception:
                    pass
                db.commit()
                return None
        except Exception:
            pass
        return row


def _google_oauth_config() -> Dict | None:
    client_id = os.getenv("GOOGLE_CLIENT_ID")
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET")
    redirect_uri = os.getenv("GOOGLE_OAUTH_REDIRECT_URI")
    if not (client_id and client_secret and redirect_uri):
        return None
    return {
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
    }


class RegisterPayload(BaseModel):
    email: EmailStr
    name: str | None = None
    password: str


class LoginPayload(BaseModel):
    email: EmailStr
    password: str
    mfa_stepup_token: str | None = None


class ApiKeyCookiePayload(BaseModel):
    api_key: str


class RefreshPayload(BaseModel):
    refresh_token: str


class AccountRecoveryRequestPayload(BaseModel):
    email: EmailStr
    reason: str | None = None


@router.post("/register")
def register(payload: RegisterPayload, request: Request, response: Response) -> Dict:
    with tracer.start_as_current_span("auth.register") as span:
        _ensure_auth_tables()
        email = payload.email.strip().lower()
        span.set_attribute("auth.email_domain", email.split("@")[-1] if "@" in email else "unknown")
        salt = secrets.token_hex(16)
        pwd_hash = _hash_password(payload.password, salt)
        user_id = secrets.token_hex(16)
        try:
            with db_session() as db:
                exists = db.execute(sql_text("SELECT 1 FROM user_accounts WHERE email = :email"), {"email": email}).scalar()
                if exists:
                    raise HTTPException(status_code=409, detail="Email already registered")
                db.execute(
                    "INSERT INTO user_accounts (id, email, name, password_hash, salt) VALUES (:id, :email, :name, :ph, :salt)",
                    {"id": user_id, "email": email, "name": payload.name, "ph": pwd_hash, "salt": salt},
                )
                # Keep customers table in sync for account UI convenience
                db.execute(
                    "INSERT INTO customers (id, email, email_hash, email_encrypted, name, created_at) VALUES (:id, :email, :email_hash, :email_encrypted, :name, CURRENT_TIMESTAMP) ON CONFLICT (id) DO NOTHING",
                    {
                        "id": user_id,
                        "email": "REDACTED",
                        "email_hash": pii_hash(email),
                        "email_encrypted": encrypt_pii(email),
                        "name": payload.name or email.split("@")[0],
                    },
                )
                db.commit()
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))
        token = _issue_token(user_id)
        jwt_pair = _issue_jwt_pair(user_id=user_id, email=email, role=_jwt_default_role())
        _set_session_cookie(response, str(token.get("token") or ""), request)
        try:
            set_csrf_cookie(response.headers, generate_csrf_token(), secure=_is_https_request(request))
        except Exception:
            pass
        return {"user_id": user_id, "email": email, "name": payload.name, **token, **jwt_pair}


@router.post("/login")
def login(payload: LoginPayload, request: Request, response: Response) -> Dict:
    with tracer.start_as_current_span("auth.login") as span:
        _ensure_auth_tables()
        email = payload.email.strip().lower()
        span.set_attribute("auth.email_domain", email.split("@")[-1] if "@" in email else "unknown")
        with db_session() as db:
            row = db.execute(
                "SELECT id, password_hash, salt, name FROM user_accounts WHERE email = :email",
                {"email": email},
            ).fetchone()
            if not row:
                try:
                    log_iam_event("login_failure", email, request.client.host if request.client else "unknown", request.headers.get("user-agent", ""), False, {"reason": "invalid_user"})
                    reason = check_bruteforce(email)
                    if reason:
                        emit_iam_anomaly(email, request.client.host if request.client else "unknown", reason)
                except Exception:
                    pass
                raise HTTPException(status_code=401, detail="Invalid credentials")
            user_id, ph, salt, name = row[0], row[1], row[2], row[3]
            _pw_valid, _pw_upgrade = _verify_password(payload.password, ph, salt)
            if not _pw_valid:
                try:
                    log_iam_event("login_failure", email, request.client.host if request.client else "unknown", request.headers.get("user-agent", ""), False, {"reason": "bad_password"})
                    reason = check_bruteforce(email)
                    if reason:
                        emit_iam_anomaly(email, request.client.host if request.client else "unknown", reason)
                except Exception:
                    pass
                raise HTTPException(status_code=401, detail="Invalid credentials")
            # Lazy hash migration: PBKDF2 → argon2id (or argon2id param refresh)
            if _pw_upgrade:
                try:
                    db.execute(
                        sql_text("UPDATE user_accounts SET password_hash = :h, salt = '' WHERE id = :uid"),
                        {"h": _pw_upgrade, "uid": str(user_id)},
                    )
                    db.commit()
                except Exception:
                    pass
        # Forced reauth policy requires explicit step-up token before issuing a new session.
        if _is_forced_reauth(user_id=str(user_id or ""), email=email):
            provided = str(payload.mfa_stepup_token or "").strip()
            expected = str(os.getenv("LOCAL_MFA_STEPUP_TOKEN", "stepup-ok")).strip()
            if not provided or provided != expected:
                raise HTTPException(status_code=403, detail="mfa_stepup_required")
            _clear_forced_reauth(user_id=str(user_id or ""), email=email)
        token = _issue_token(user_id)
        jwt_pair = _issue_jwt_pair(user_id=str(user_id), email=email, role=_jwt_default_role())
        _set_session_cookie(response, str(token.get("token") or ""), request)
        # Set JWT access + refresh tokens as httpOnly cookies (XSS-safe)
        _secure = _is_https_request(request)
        if jwt_pair.get("access_token"):
            response.set_cookie(
                key="shopsquire_access",
                value=str(jwt_pair["access_token"]),
                httponly=True,
                secure=_secure,
                samesite="strict",
                max_age=int(jwt_pair.get("access_expires_in", 900)),
                path="/",
            )
        if jwt_pair.get("refresh_token"):
            response.set_cookie(
                key="shopsquire_refresh",
                value=str(jwt_pair["refresh_token"]),
                httponly=True,
                secure=_secure,
                samesite="strict",
                max_age=int(jwt_pair.get("refresh_expires_in", 86400)),
                path="/api/v1/auth",
            )
        try:
            set_csrf_cookie(response.headers, generate_csrf_token(), secure=_secure)
        except Exception:
            pass
        try:
            log_iam_event("login_success", email, request.client.host if request.client else "unknown", request.headers.get("user-agent", ""), True, {"user_id": user_id})
            reason = check_impossible_travel(email, request.client.host if request.client else "unknown")
            if reason:
                emit_iam_anomaly(email, request.client.host if request.client else "unknown", reason)
        except Exception:
            pass
        return {"user_id": user_id, "email": email, "name": name, **token, **jwt_pair}


@router.post("/logout")
def logout(
    response: Response,
    token: str | None = None,
    shopsquire_session: str | None = Cookie(default=None),
) -> Dict:
    with tracer.start_as_current_span("auth.logout"):
        _ensure_auth_tables()
        token_value = str(token or shopsquire_session or "")
        token_hash = hashlib.sha256(token_value.encode("utf-8")).hexdigest() if token_value else ""
        with db_session() as db:
            user_row = None
            try:
                user_row = _user_from_token(token_value)
            except Exception:
                user_row = None
            # Delete by hash if present, else token
            try:
                db.execute(sql_text("DELETE FROM session_tokens WHERE token_hash = :th"), {"th": token_hash})
            except Exception:
                db.execute(sql_text("DELETE FROM session_tokens WHERE token = :t"), {"t": token_value})
            try:
                if user_row and user_row[0]:
                    db.execute(
                        "UPDATE refresh_tokens SET revoked_at = CURRENT_TIMESTAMP WHERE user_id = :uid AND revoked_at IS NULL",
                        {"uid": str(user_row[0])},
                    )
            except Exception:
                pass
            db.commit()
        _clear_session_cookie(response)
        return {"logged_out": True}


@router.post("/account-recovery/request")
def request_account_recovery(payload: AccountRecoveryRequestPayload) -> Dict:
    _ensure_auth_tables()
    email = str(payload.email or "").strip().lower()
    if not email:
        raise HTTPException(status_code=400, detail="email_required")

    verdict = evaluate_action_authority(
        "account_recovery",
        value_aud_cents=0,
        context={"email_domain": email.split("@")[-1] if "@" in email else "unknown"},
    )
    if verdict.decision == AuthDecision.BLOCK:
        raise HTTPException(
            status_code=403,
            detail={
                "error": "policy_gate_denied",
                "action": "account_recovery",
                "decision": verdict.decision.value,
                "reason": verdict.reason,
                "rule_id": verdict.rule_id,
            },
        )

    known_user_id = None
    try:
        with db_session() as db:
            row = db.execute(
                "SELECT id FROM user_accounts WHERE lower(email) = :email LIMIT 1",
                {"email": email},
            ).fetchone()
            if row and row[0]:
                known_user_id = str(row[0]).strip()
                db.execute(
                    """
                    INSERT INTO security_forced_reauth_flags
                    (id, target_type, target_value, reason, created_at)
                    VALUES (:id, 'email', :target_value, :reason, CURRENT_TIMESTAMP)
                    ON CONFLICT (id) DO UPDATE SET reason = EXCLUDED.reason, created_at = EXCLUDED.created_at
                    """,
                    {
                        "id": f"fr-{secrets.token_hex(12)}",
                        "target_value": email,
                        "reason": str(payload.reason or "account_recovery_requested").strip()[:255],
                    },
                )
                db.execute(
                    """
                    INSERT INTO security_forced_reauth_flags
                    (id, target_type, target_value, reason, created_at)
                    VALUES (:id, 'user_id', :target_value, :reason, CURRENT_TIMESTAMP)
                    ON CONFLICT (id) DO UPDATE SET reason = EXCLUDED.reason, created_at = EXCLUDED.created_at
                    """,
                    {
                        "id": f"fr-{secrets.token_hex(12)}",
                        "target_value": known_user_id,
                        "reason": str(payload.reason or "account_recovery_requested").strip()[:255],
                    },
                )
                db.commit()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"account_recovery_request_failed: {exc}")

    return {
        "status": "pending_review",
        "decision": verdict.decision.value,
        "reason": verdict.reason,
        "rule_id": verdict.rule_id,
        "ticket_priority": verdict.ticket_priority,
        "known_account": bool(known_user_id),
    }


@router.get("/me")
def me(token: str | None = None, shopsquire_session: str | None = Cookie(default=None)) -> Dict:
    with tracer.start_as_current_span("auth.me"):
        _ensure_auth_tables()
        row = _user_from_token(str(token or shopsquire_session or ""))
        if not row:
            raise HTTPException(status_code=401, detail="Invalid token")
        return {"user_id": row[0], "email": row[1], "name": row[2]}


@router.post("/token/refresh")
def refresh_token(payload: RefreshPayload) -> Dict:
    _ensure_auth_tables()
    refresh_token_value = str(payload.refresh_token or "").strip()
    if not refresh_token_value:
        raise HTTPException(status_code=400, detail="refresh_token_required")
    claims = _decode_refresh_jwt(refresh_token_value)
    if not claims:
        raise HTTPException(status_code=401, detail="invalid_refresh_token")
    rotated = _rotate_refresh_token(refresh_token_value)
    if not rotated:
        raise HTTPException(status_code=401, detail="refresh_token_revoked_or_expired")
    access = _issue_access_jwt(
        user_id=str(claims.get("sub") or ""),
        email=str(claims.get("email") or ""),
        role=str(claims.get("role") or _jwt_default_role()),
    )
    return {
        "access_token": access.get("token"),
        "access_expires_in": int(access.get("expires_in") or 0),
        "refresh_token": rotated.get("token"),
        "refresh_expires_in": int(rotated.get("expires_in") or 0),
    }


@router.post("/api-key-cookie")
def set_api_key_cookie(payload: ApiKeyCookiePayload, request: Request, response: Response) -> Dict:
    key = str(payload.api_key or "").strip()
    if not key:
        raise HTTPException(status_code=400, detail="api_key_required")
    _set_api_key_cookie(response, key, request)
    return {"ok": True}


@router.delete("/api-key-cookie")
def clear_api_key_cookie(response: Response) -> Dict:
    _clear_api_key_cookie(response)
    return {"ok": True}


@router.get("/google/authorize")
def google_authorize(return_to: str | None = None):
    with tracer.start_as_current_span("auth.google_authorize"):
        _ensure_auth_tables()
        config = _google_oauth_config()
        if not config:
            raise HTTPException(status_code=503, detail="Google OAuth not configured")
        safe_return = return_to if return_to and return_to.startswith("/") else "/ui/account"
        state = secrets.token_urlsafe(16)
        # PKCE: verifier + S256 code challenge; Nonce for OIDC
        code_verifier = secrets.token_urlsafe(64)
        import base64
        code_challenge = base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode("utf-8")).digest()).decode("utf-8").rstrip("=")
        nonce = secrets.token_urlsafe(16)
        expires_at = (datetime.utcnow() + timedelta(minutes=10)).isoformat()
        with db_session() as db:
            db.execute(
                "INSERT INTO oauth_states (state, return_to, expires_at, code_verifier, nonce) VALUES (:state, :return_to, :expires_at, :cv, :nonce)",
                {"state": state, "return_to": safe_return, "expires_at": expires_at, "cv": code_verifier, "nonce": nonce},
            )
            db.commit()
        params = {
            "client_id": config["client_id"],
            "redirect_uri": config["redirect_uri"],
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
            "access_type": "offline",
            "prompt": "select_account",
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "nonce": nonce,
        }
        url = "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params)
        return RedirectResponse(url=url)


@router.get("/google/callback")
def google_callback(code: str | None = None, state: str | None = None):
    with tracer.start_as_current_span("auth.google_callback"):
        _ensure_auth_tables()
        config = _google_oauth_config()
        if not config:
            raise HTTPException(status_code=503, detail="Google OAuth not configured")
        if not code or not state:
            raise HTTPException(status_code=400, detail="Missing code or state")
        with db_session() as db:
            row = db.execute(
                "SELECT return_to, expires_at, code_verifier, nonce FROM oauth_states WHERE state = :state",
                {"state": state},
            ).fetchone()
            db.execute(sql_text("DELETE FROM oauth_states WHERE state = :state"), {"state": state})
            db.commit()
        if not row:
            raise HTTPException(status_code=400, detail="Invalid state")
        return_to = row[0] or "/ui/account"
        try:
            expires_at = row[1]
            if expires_at and datetime.utcnow() > datetime.fromisoformat(str(expires_at)):
                raise HTTPException(status_code=400, detail="State expired")
        except HTTPException:
            raise
        except Exception:
            pass

        token_payload = {
            "code": code,
            "client_id": config["client_id"],
            "client_secret": config["client_secret"],
            "redirect_uri": config["redirect_uri"],
            "grant_type": "authorization_code",
        }
        # Include PKCE code_verifier if available
        try:
            cv = row[2] if row and len(row) > 2 else None
            if cv:
                token_payload["code_verifier"] = cv
        except Exception:
            pass
        try:
            with httpx.Client(timeout=10) as client:
                token_res = client.post("https://oauth2.googleapis.com/token", data=token_payload)
                token_res.raise_for_status()
                tokens = token_res.json()
                access_token = tokens.get("access_token")
                if not access_token:
                    raise HTTPException(status_code=400, detail="Missing access token")
                userinfo = client.get(
                    "https://www.googleapis.com/oauth2/v3/userinfo",
                    headers={"Authorization": f"Bearer {access_token}"},
                )
                userinfo.raise_for_status()
                profile = userinfo.json()
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc))

        email = (profile.get("email") or "").strip().lower()
        if not email:
            raise HTTPException(status_code=400, detail="Google account missing email")
        if profile.get("email_verified") is False:
            raise HTTPException(status_code=400, detail="Email not verified")
        provider_user_id = profile.get("sub") or profile.get("id")
        if not provider_user_id:
            raise HTTPException(status_code=400, detail="Google account missing id")
        name = profile.get("name")

        with db_session() as db:
            existing = db.execute(
                "SELECT user_id FROM oauth_identities WHERE provider = :p AND provider_user_id = :pid",
                {"p": "google", "pid": provider_user_id},
            ).fetchone()
            if existing:
                user_id = existing[0]
            else:
                row = db.execute(
                    "SELECT id, name FROM user_accounts WHERE email = :email",
                    {"email": email},
                ).fetchone()
                if row:
                    user_id = row[0]
                    if not row[1] and name:
                        db.execute(
                            "UPDATE user_accounts SET name = :name WHERE id = :id",
                            {"name": name, "id": user_id},
                        )
                else:
                    user_id = secrets.token_hex(16)
                    salt = secrets.token_hex(16)
                    pwd_hash = _hash_password(secrets.token_urlsafe(16), salt)
                    db.execute(
                        "INSERT INTO user_accounts (id, email, name, password_hash, salt) VALUES (:id, :email, :name, :ph, :salt)",
                        {"id": user_id, "email": email, "name": name, "ph": pwd_hash, "salt": salt},
                    )
                db.execute(
                    "INSERT INTO oauth_identities (id, provider, provider_user_id, user_id, email) VALUES (:id, :p, :pid, :uid, :email)",
                    {
                        "id": secrets.token_hex(16),
                        "p": "google",
                        "pid": provider_user_id,
                        "uid": user_id,
                        "email": email,
                    },
                )
            db.execute(
                "INSERT INTO customers (id, email, email_hash, email_encrypted, name, created_at) VALUES (:id, :email, :email_hash, :email_encrypted, :name, CURRENT_TIMESTAMP) ON CONFLICT (id) DO NOTHING",
                {
                    "id": user_id,
                    "email": "REDACTED",
                    "email_hash": pii_hash(email),
                    "email_encrypted": encrypt_pii(email),
                    "name": name or email.split("@")[0],
                },
            )
            db.commit()

        token = _issue_token(user_id)
        resp = RedirectResponse(url=return_to, status_code=302)
        _set_session_cookie(resp, str(token.get("token") or ""), None)
        return resp
