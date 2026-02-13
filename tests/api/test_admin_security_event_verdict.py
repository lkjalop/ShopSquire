from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from src.app.main import create_app
from src.app.models.db import db_session, set_engine


def test_set_security_event_correction_verdict(monkeypatch, tmp_path):
    db_path = tmp_path / "security_verdict.sqlite"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+pysqlite:///{db_path}")
    eng = create_engine(f"sqlite+pysqlite:///{db_path}", connect_args={"check_same_thread": False}, future=True)
    set_engine(eng)
    try:
        import src.app.models.db as dbmod

        dbmod.SessionLocal = sessionmaker(bind=eng, future=True)
    except Exception:
        pass

    with db_session() as db:
        db.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS security_events (
                  id TEXT PRIMARY KEY,
                  event_time TEXT DEFAULT CURRENT_TIMESTAMP,
                  path TEXT,
                  severity TEXT,
                  verdict_score INT,
                  details TEXT,
                  escalated INTEGER DEFAULT 0,
                  blocked INTEGER DEFAULT 0
                )
                """
            )
        )
        db.execute(
            text(
                """
                INSERT INTO security_events (id, path, severity, verdict_score, details)
                VALUES ('ev-1', '/api/test', 'high', 92, '{}')
                """
            )
        )
        db.commit()

    client = TestClient(create_app())
    r = client.post(
        "/api/v1/admin/security/events/ev-1/verdict",
        json={
            "ground_truth": "false_positive",
            "analyst_verdict": "overridden",
            "correction_notes": "manual validation determined benign",
        },
        headers={"x-api-key": "local-owner-key"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body.get("updated") is True
    assert body.get("ground_truth") == "false_positive"

    r2 = client.get("/api/v1/admin/security/events/ev-1", headers={"x-api-key": "local-owner-key"})
    assert r2.status_code == 200
    ev = r2.json()
    assert ev.get("ground_truth") == "false_positive"
    assert ev.get("analyst_verdict") == "overridden"
