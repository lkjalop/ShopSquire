from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.app.main import create_app
from src.app.models.db import set_engine


def _client(tmp_path, monkeypatch):
    db_path = tmp_path / "privacy_consent.sqlite"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+pysqlite:///{db_path}")
    eng = create_engine(f"sqlite+pysqlite:///{db_path}", connect_args={"check_same_thread": False}, future=True)
    set_engine(eng)
    try:
        import src.app.models.db as dbmod

        dbmod.SessionLocal = sessionmaker(bind=eng, future=True)
    except Exception:
        pass
    return TestClient(create_app())


def test_privacy_consent_set_and_get(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    uid = "u_privacy_1"
    payload = {
        "personalization_opt_in": True,
        "retention_opt_in": True,
        "ai_disclosure_ack": True,
        "locale": "en",
    }
    r1 = client.post(f"/api/v1/privacy/consent/{uid}", json=payload, headers={"x-api-key": "local-merchant-key"})
    assert r1.status_code == 200
    b1 = r1.json()
    assert b1.get("ok") is True
    assert (b1.get("consent") or {}).get("personalization_opt_in") is True

    r2 = client.get(f"/api/v1/privacy/consent/{uid}", headers={"x-api-key": "local-merchant-key"})
    assert r2.status_code == 200
    b2 = r2.json()
    assert (b2.get("consent") or {}).get("retention_opt_in") is True


def test_privacy_request_create(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    uid = "u_privacy_2"
    r = client.post(
        f"/api/v1/privacy/request/{uid}",
        json={"request_type": "export", "reason": "user_requested"},
        headers={"x-api-key": "local-merchant-key"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body.get("ok") is True
    req = body.get("request") or {}
    assert req.get("request_type") == "export"
    assert str(req.get("id") or "").startswith("prv_")

