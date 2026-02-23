from fastapi.testclient import TestClient
from sqlalchemy import text


def test_force_reauth_action_revokes_session_tokens_for_explicit_identity():
    from src.app.main import create_app
    from src.app.models.db import db_session

    client = TestClient(create_app())
    user_id = "usr-force-reauth-1"
    email = "force.reauth@example.com"
    incident_id = "esi-force-reauth-1"

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
                CREATE TABLE IF NOT EXISTS email_security_incidents (
                  id TEXT PRIMARY KEY,
                  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                  tenant_id TEXT,
                  provider TEXT,
                  supplier_key_hash TEXT,
                  ticket_id TEXT,
                  severity TEXT,
                  risk_band TEXT,
                  playbook_id TEXT,
                  playbook_title TEXT,
                  tags_json TEXT,
                  reasons_json TEXT,
                  evidence_json TEXT,
                  ticket_created INTEGER,
                  ticket_rate_limited INTEGER,
                  ticket_deduped INTEGER
                )
                """
            )
        )
        db.execute(
            text(
                """
                INSERT OR REPLACE INTO user_accounts (id, email, name, password_hash, salt)
                VALUES (:id, :email, 'Force Reauth User', 'hash', 'salt')
                """
            ),
            {"id": user_id, "email": email},
        )
        try:
            db.execute(
                text(
                    """
                    INSERT OR REPLACE INTO session_tokens (id, user_id, token, token_hash, expires_at)
                    VALUES ('sess-force-1', :uid, 'tok-force-1', NULL, '2099-01-01T00:00:00')
                    """
                ),
                {"uid": user_id},
            )
        except Exception:
            db.execute(
                text(
                    """
                    INSERT OR REPLACE INTO session_tokens (id, user_id, token, expires_at)
                    VALUES ('sess-force-1', :uid, 'tok-force-1', '2099-01-01T00:00:00')
                    """
                ),
                {"uid": user_id},
            )
        db.execute(
            text(
                """
                INSERT OR REPLACE INTO email_security_incidents
                (id, severity, tags_json, reasons_json, evidence_json)
                VALUES (:id, 'error', '[]', '[]', '{}')
                """
            ),
            {"id": incident_id},
        )
        db.commit()

    r = client.post(
        f"/api/v1/admin/email_security/investigations/{incident_id}/action",
        headers={"x-api-key": "local-owner-key"},
        json={
            "action": "force_reauth",
            "note": "integration test",
            "user_id": user_id,
            "email": email,
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("status") == "executed"
    execution = body.get("execution") or {}
    assert execution.get("executed") is True
    session_revoke = execution.get("session_revoke") or {}
    assert int(session_revoke.get("revoked_tokens") or 0) >= 1

    with db_session() as db:
        left = db.execute(
            text("SELECT COUNT(*) FROM session_tokens WHERE user_id = :uid"),
            {"uid": user_id},
        ).scalar()
    assert int(left or 0) == 0
