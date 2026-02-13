from fastapi.testclient import TestClient

from src.app.main import create_app
from tests.utils import default_headers


app = create_app()
client = TestClient(app)


def test_jobs_queue_health_endpoint():
    r = client.get("/api/v1/jobs/health/queues", headers=default_headers())
    assert r.status_code == 200
    data = r.json()
    assert data.get("ok") in (True, False)
    assert "stats" in data
    assert "autoscale_hints" in data or data.get("ok") is False
