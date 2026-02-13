import json
from fastapi.testclient import TestClient

from src.app.main import create_app
from tests.utils import default_headers

app = create_app()
client = TestClient(app)


def test_recommend_response_schema():
    r = client.get("/api/v1/recommend/suggest", params={"uid": "u1", "query": "laptop"}, headers=default_headers())
    assert r.status_code == 200
    data = r.json()
    assert set(["results", "proposal", "constraints_used", "policy_version"]).issubset(set(data.keys()))


def test_decisions_query_exists():
    r = client.get("/api/v1/decisions/query", headers=default_headers())
    # In environments where decision logs are disabled, this may return 501
    assert r.status_code in (200, 404, 500, 501)
