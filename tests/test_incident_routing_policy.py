from fastapi.testclient import TestClient
from src.app.main import create_app
from tests.utils import default_headers

app = create_app()

client = TestClient(app, headers=default_headers())


def test_incident_uses_routing_policy_threshold():
    r = client.post("/api/v1/incident/alert", params={"topic": "governance", "message": "config change"})
    assert r.status_code == 200
    data = r.json()
    assert data["severity"] in ("p2", "p1", "p3")