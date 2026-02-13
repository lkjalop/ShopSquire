from __future__ import annotations

import hashlib
import os
import secrets
from datetime import datetime, timedelta
from typing import Dict
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, EmailStr

from src.app.models.db import db_session
from src.app.security.iam import log_iam_event, check_bruteforce, check_impossible_travel, emit_iam_anomaly
from src.app.observability.tracing import get_tracer
from src.app.services.pii_crypto import encrypt_pii, pii_hash
import httpx


router = APIRouter(prefix="/api/v1/auth", tags=["auth"])
tracer = get_tracer("auth-router")


def _ensure_auth_tables():
    # Alembic is the source of truth for non-SQLite DBs.
    try:
        from src.app.models.db import get_engine

        eng = get_engine()
        if getattr(eng, "dialect", None) is not None and eng.dialect.name != "sqlite":
            return
    except Exception:
        pass

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
        # Backward-compatible schema updates
        try:
            db.execute("ALTER TABLE session_tokens ADD COLUMN token_hash TEXT")
        except Exception:
            pass
        try:
            db.execute("ALTER TABLE oauth_states ADD COLUMN code_verifier TEXT")
        except Exception:
            pass
        try:
            db.execute("ALTER TABLE oauth_states ADD COLUMN nonce TEXT")
        except Exception:
            pass
        db.commit()


def _hash_password(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 100000).hex()


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
            db.execute(
                "INSERT INTO session_tokens (id, user_id, token, token_hash, expires_at) VALUES (:id, :user_id, :token, :token_hash, :expires_at)",
                {"id": secrets.token_hex(16), "user_id": user_id, "token": None, "token_hash": token_hash, "expires_at": expires_at},
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
                    db.execute("DELETE FROM session_tokens WHERE token_hash = :th", {"th": token_hash})
                except Exception:
                    db.execute("DELETE FROM session_tokens WHERE token = :t", {"t": token})
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


@router.post("/register")
def register(payload: RegisterPayload) -> Dict:
    with tracer.start_as_current_span("auth.register") as span:
        _ensure_auth_tables()
        email = payload.email.strip().lower()
        span.set_attribute("auth.email_domain", email.split("@")[-1] if "@" in email else "unknown")
        salt = secrets.token_hex(16)
        pwd_hash = _hash_password(payload.password, salt)
        user_id = secrets.token_hex(16)
        try:
            with db_session() as db:
                exists = db.execute("SELECT 1 FROM user_accounts WHERE email = :email", {"email": email}).scalar()
                if exists:
                    raise HTTPException(status_code=409, detail="Email already registered")
                db.execute(
                    "INSERT INTO user_accounts (id, email, name, password_hash, salt) VALUES (:id, :email, :name, :ph, :salt)",
                    {"id": user_id, "email": email, "name": payload.name, "ph": pwd_hash, "salt": salt},
                )
                # Keep customers table in sync for account UI convenience
                db.execute(
                    "INSERT OR IGNORE INTO customers (id, email, email_hash, email_encrypted, name, created_at) VALUES (:id, :email, :email_hash, :email_encrypted, :name, CURRENT_TIMESTAMP)",
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
        return {"user_id": user_id, "email": email, "name": payload.name, **token}


@router.post("/login")
def login(payload: LoginPayload, request: Request) -> Dict:
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
            if _hash_password(payload.password, salt) != ph:
                try:
                    log_iam_event("login_failure", email, request.client.host if request.client else "unknown", request.headers.get("user-agent", ""), False, {"reason": "bad_password"})
                    reason = check_bruteforce(email)
                    if reason:
                        emit_iam_anomaly(email, request.client.host if request.client else "unknown", reason)
                except Exception:
                    pass
                raise HTTPException(status_code=401, detail="Invalid credentials")
        token = _issue_token(user_id)
        try:
            log_iam_event("login_success", email, request.client.host if request.client else "unknown", request.headers.get("user-agent", ""), True, {"user_id": user_id})
            reason = check_impossible_travel(email, request.client.host if request.client else "unknown")
            if reason:
                emit_iam_anomaly(email, request.client.host if request.client else "unknown", reason)
        except Exception:
            pass
        return {"user_id": user_id, "email": email, "name": name, **token}


@router.post("/logout")
def logout(token: str) -> Dict:
    with tracer.start_as_current_span("auth.logout"):
        _ensure_auth_tables()
        token_hash = hashlib.sha256((token or "").encode("utf-8")).hexdigest() if token else ""
        with db_session() as db:
            # Delete by hash if present, else token
            try:
                db.execute("DELETE FROM session_tokens WHERE token_hash = :th", {"th": token_hash})
            except Exception:
                db.execute("DELETE FROM session_tokens WHERE token = :t", {"t": token})
            db.commit()
        return {"logged_out": True}


@router.get("/me")
def me(token: str) -> Dict:
    with tracer.start_as_current_span("auth.me"):
        _ensure_auth_tables()
        row = _user_from_token(token)
        if not row:
            raise HTTPException(status_code=401, detail="Invalid token")
        return {"user_id": row[0], "email": row[1], "name": row[2]}


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
            db.execute("DELETE FROM oauth_states WHERE state = :state", {"state": state})
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
                "INSERT OR IGNORE INTO customers (id, email, email_hash, email_encrypted, name, created_at) VALUES (:id, :email, :email_hash, :email_encrypted, :name, CURRENT_TIMESTAMP)",
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
        html = f"""
        <!doctype html>
        <html lang="en">
        <head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"></head>
        <body>
          <script>
            localStorage.setItem('shopsquire_session_token', '{token["token"]}');
            localStorage.setItem('shopsquire_session_expires', '{token["expires_at"]}');
            window.location.href = '{return_to}';
          </script>
          <p>Signing you in...</p>
        </body>
        </html>
        """
        return HTMLResponse(content=html)
