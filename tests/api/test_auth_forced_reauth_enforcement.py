from fastapi.testclient import TestClient
from sqlalchemy import text


def test_forced_reauth_blocks_existing_session_token():
    from src.app.main import create_app
    from src.app.models.db import db_session

    client = TestClient(create_app())
    user_id = "usr-auth-forced-1"
    email = "auth.forced1@example.com"
    token = "tok-auth-forced-1"

    with db_session() as db:
        db.execute(
            text(
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
        )
        db.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS session_tokens (
                  id TEXT PRIMARY KEY,
                  user_id TEXT NOT NULL,
                  token TEXT,
                  token_hash TEXT,
                  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                  expires_at TEXT
                )
                """
            )
        )
        db.execute(
            text(
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
        )
        db.execute(
            text(
                """
                INSERT OR REPLACE INTO user_accounts (id, email, name, password_hash, salt)
                VALUES (:id, :email, 'Auth Forced', 'hash', 'salt')
                """
            ),
            {"id": user_id, "email": email},
        )
        try:
            db.execute(
                text(
                    """
                    INSERT OR REPLACE INTO session_tokens (id, user_id, token, token_hash, expires_at)
                    VALUES ('sess-auth-forced-1', :uid, :tok, NULL, '2099-01-01T00:00:00')
                    """
                ),
                {"uid": user_id, "tok": token},
            )
        except Exception:
            db.execute(
                text(
                    """
                    INSERT OR REPLACE INTO session_tokens (id, user_id, token, expires_at)
                    VALUES ('sess-auth-forced-1', :uid, :tok, '2099-01-01T00:00:00')
                    """
                ),
                {"uid": user_id, "tok": token},
            )
        db.execute(
            text(
                """
                INSERT OR REPLACE INTO security_forced_reauth_flags (id, target_type, target_value, reason, created_at)
                VALUES ('fr-auth-1', 'user_id', :uid, 'test', CURRENT_TIMESTAMP)
                """
            ),
            {"uid": user_id},
        )
        db.commit()

    r = client.get("/api/v1/auth/me", params={"token": token})
    assert r.status_code == 401

    with db_session() as db:
        left = db.execute(text("SELECT COUNT(*) FROM session_tokens WHERE user_id = :uid"), {"uid": user_id}).scalar()
    assert int(left or 0) == 0


def test_forced_reauth_requires_stepup_on_login_then_clears_flag():
    from src.app.main import create_app
    from src.app.models.db import db_session
    from src.app.routers.auth import _hash_password

    client = TestClient(create_app())
    user_id = "usr-auth-forced-2"
    email = "auth.forced2@example.com"
    password = "Secret123!"
    salt = "salt2"

    with db_session() as db:
        db.execute(
            text(
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
        )
        db.execute(
            text(
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
        )
        db.execute(
            text(
                """
                INSERT OR REPLACE INTO user_accounts (id, email, name, password_hash, salt)
                VALUES (:id, :email, 'Auth Forced2', :ph, :salt)
                """
            ),
            {"id": user_id, "email": email, "ph": _hash_password(password, salt), "salt": salt},
        )
        db.execute(
            text(
                """
                INSERT OR REPLACE INTO security_forced_reauth_flags (id, target_type, target_value, reason, created_at)
                VALUES ('fr-auth-2', 'email', :email, 'test', CURRENT_TIMESTAMP)
                """
            ),
            {"email": email},
        )
        db.commit()

    r1 = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert r1.status_code == 403
    assert (r1.json() or {}).get("detail") == "mfa_stepup_required"

    r2 = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password, "mfa_stepup_token": "stepup-ok"},
    )
    assert r2.status_code == 200
    assert bool((r2.json() or {}).get("token"))

    with db_session() as db:
        still_flagged = db.execute(
            text(
                "SELECT COUNT(*) FROM security_forced_reauth_flags "
                "WHERE target_type = 'email' AND lower(target_value) = :email"
            ),
            {"email": email.lower()},
        ).scalar()
    assert int(still_flagged or 0) == 0

