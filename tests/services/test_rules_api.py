import json
import os
from fastapi.testclient import TestClient

from src.app.main import create_app
from src.app.models.db import db_session, set_engine
from sqlalchemy import text, create_engine
from sqlalchemy.orm import sessionmaker


def ensure_table():
    with db_session() as db:
        db.execute(
            text(
                "CREATE TABLE IF NOT EXISTS rule_definitions ("
                "id TEXT PRIMARY KEY, "
                "tenant_id TEXT, "
                "domain TEXT, "
                "title TEXT, "
                "pattern TEXT, "
                "expression TEXT, "
                "priority INTEGER, "
                "active INTEGER, "
                "created_by TEXT, "
                "version TEXT, "
                "effective_from TEXT, "
                "effective_to TEXT, "
                "created_at TEXT)"
            )
        )
        db.commit()


def test_rules_crud_and_preview(tmp_path):
    # Isolate DB for this test to avoid interference from long-running test servers
    db_path = tmp_path / "rules.sqlite"
    os.environ["DATABASE_URL"] = f"sqlite+pysqlite:///{db_path}"
    eng = create_engine(f"sqlite+pysqlite:///{db_path}", connect_args={"check_same_thread": False}, future=True)
    set_engine(eng)
    try:
        import src.app.models.db as dbmod
        dbmod.SessionLocal = sessionmaker(bind=eng, future=True)
    except Exception:
        pass
    ensure_table()
    app = create_app()
    client = TestClient(app)

    # Use developer key
    headers = {"x-api-key": "local-developer-key"}

    # Create rule
    payload = {"id": "r_api_test", "title": "api_test", "pattern": "hello\\s+world", "priority": 50}
    r = client.post('/api/v1/rules/', headers=headers, json=payload)
    assert r.status_code == 200
    rid = r.json().get("id") or payload["id"]

    # List rules
    r = client.get('/api/v1/rules/', headers=headers)
    assert r.status_code == 200
    rules = r.json().get("rules") or []
    assert any(rr.get("id") == rid for rr in rules)

    # Preview
    pr = client.post('/api/v1/rules/preview', headers=headers, json={"text": "hello world"})
    assert pr.status_code == 200
    body = pr.json()
    assert isinstance(body, dict)

    # Update: reject invalid regex
    bad = client.put(f"/api/v1/rules/{rid}", headers=headers, json={"pattern": "("})
    assert bad.status_code == 400

    # Tenant scoping: create tenant-specific rule and ensure it only shows with tenant_id
    r2 = client.post('/api/v1/rules/', headers=headers, json={"id": "tenant_rule", "tenant_id": "t1", "title": "tenant_only", "pattern": "tenant", "priority": 5})
    assert r2.status_code == 200
    all_rules = client.get('/api/v1/rules/', headers=headers).json().get("rules") or []
    t1_rules = client.get('/api/v1/rules/?tenant_id=t1', headers=headers).json().get("rules") or []
    assert any(rr.get("id") == "tenant_rule" for rr in t1_rules)
    assert not any(rr.get("id") == "tenant_rule" for rr in all_rules)

    # Delete
    dr = client.delete(f"/api/v1/rules/{rid}", headers=headers)
    assert dr.status_code == 200
