from fastapi.testclient import TestClient
from sqlalchemy import text


def test_account_recovery_request_sets_forced_reauth_for_known_account():
    from src.app.main import create_app
    from src.app.models.db import db_session
    from src.app.routers.auth import _hash_password

    client = TestClient(create_app())
    user_id = "usr-auth-recovery-1"
    email = "recover.known@example.com"

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
                INSERT OR REPLACE INTO user_accounts (id, email, name, password_hash, salt)
                VALUES (:id, :email, 'Recovery User', :ph, 'salt-recover')
                """
            ),
            {"id": user_id, "email": email, "ph": _hash_password("Password123!", "salt-recover")},
        )
        db.commit()

    r = client.post(
        "/api/v1/auth/account-recovery/request",
        json={"email": email, "reason": "device_lost"},
    )
    assert r.status_code == 200, r.text
    body = r.json() or {}
    assert body.get("status") == "pending_review"
    assert body.get("decision") == "human_review"
    assert body.get("known_account") is True

    with db_session() as db:
        by_email = db.execute(
            text(
                "SELECT COUNT(*) FROM security_forced_reauth_flags "
                "WHERE target_type = 'email' AND lower(target_value) = :email"
            ),
            {"email": email.lower()},
        ).scalar()
        by_user = db.execute(
            text(
                "SELECT COUNT(*) FROM security_forced_reauth_flags "
                "WHERE target_type = 'user_id' AND target_value = :uid"
            ),
            {"uid": user_id},
        ).scalar()
    assert int(by_email or 0) >= 1
    assert int(by_user or 0) >= 1


def test_account_recovery_request_is_generic_for_unknown_account():
    from src.app.main import create_app
    from src.app.models.db import db_session

    client = TestClient(create_app())
    email = "recover.unknown@example.com"

    r = client.post(
        "/api/v1/auth/account-recovery/request",
        json={"email": email},
    )
    assert r.status_code == 200, r.text
    body = r.json() or {}
    assert body.get("status") == "pending_review"
    assert body.get("decision") == "human_review"
    assert body.get("known_account") is False

    with db_session() as db:
        flagged = db.execute(
            text(
                "SELECT COUNT(*) FROM security_forced_reauth_flags "
                "WHERE target_type = 'email' AND lower(target_value) = :email"
            ),
            {"email": email.lower()},
        ).scalar()
    assert int(flagged or 0) == 0
