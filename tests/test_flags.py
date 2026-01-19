from fastapi.testclient import TestClient
from src.app.main import app


client = TestClient(app)


def test_flags_get():
    r = client.get("/api/v1/admin/flags")
    assert r.status_code == 200
    flags = r.json()
    assert "AGENT_ROLLOUT_PERCENT" in flags
