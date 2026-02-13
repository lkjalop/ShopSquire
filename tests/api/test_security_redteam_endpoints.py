from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.app.main import create_app
from src.app.models.db import set_engine


def test_redteam_run_and_benchmark_endpoints(monkeypatch, tmp_path):
    db_path = tmp_path / "redteam.sqlite"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+pysqlite:///{db_path}")
    eng = create_engine(f"sqlite+pysqlite:///{db_path}", connect_args={"check_same_thread": False}, future=True)
    set_engine(eng)
    try:
        import src.app.models.db as dbmod

        dbmod.SessionLocal = sessionmaker(bind=eng, future=True)
    except Exception:
        pass

    client = TestClient(create_app())
    r = client.post(
        "/api/v1/security/redteam/run?mutate=true&max_mutations_per_case=3&persist=true",
        headers={"x-api-key": "local-owner-key"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body.get("run_id")
    assert int(body.get("total_cases") or 0) > 0
    assert "detection_rate" in body

    r2 = client.get("/api/v1/security/redteam/benchmarks?days=30", headers={"x-api-key": "local-owner-key"})
    assert r2.status_code == 200
    b = r2.json()
    assert "runs" in b
    assert "summary" in b
    assert isinstance((b.get("summary") or {}).get("by_attack_family", {}), dict)
