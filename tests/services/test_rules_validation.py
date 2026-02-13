import os
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.app.main import create_app
from src.app.models.db import set_engine


def _client(tmp_path):
    db_path = tmp_path / "rules_validation.sqlite"
    os.environ["DATABASE_URL"] = f"sqlite+pysqlite:///{db_path}"
    eng = create_engine(f"sqlite+pysqlite:///{db_path}", connect_args={"check_same_thread": False}, future=True)
    set_engine(eng)
    try:
        import src.app.models.db as dbmod
        dbmod.SessionLocal = sessionmaker(bind=eng, future=True)
    except Exception:
        pass
    app = create_app()
    return TestClient(app)


def test_rules_reject_invalid_regex(tmp_path):
    client = _client(tmp_path)
    headers = {"x-api-key": "local-developer-key"}

    r = client.post("/api/v1/rules/", headers=headers, json={"title": "bad", "pattern": "("})
    assert r.status_code == 400
    body = r.json()
    assert body.get("detail", {}).get("error") == "invalid_regex"


def test_rules_dry_run_priority_order(tmp_path):
    client = _client(tmp_path)
    headers = {"x-api-key": "local-developer-key"}

    payload = {
        "text": "please refund my order",
        "rules": [
            {"id": "r2", "title": "product_search", "pattern": r"\bshow\s+me\b", "priority": 50},
            {"id": "r1", "title": "return_request", "pattern": r"\brefund\b", "priority": 10},
        ],
    }
    r = client.post("/api/v1/rules/dry-run", headers=headers, json=payload)
    assert r.status_code == 200
    body = r.json()
    assert body["match"]["id"] == "r1"
