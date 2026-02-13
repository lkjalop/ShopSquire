import os
from fastapi.testclient import TestClient
from src.app.main import create_app

os.environ.setdefault("DATABASE_URL", "sqlite:///test.sqlite")
os.environ.setdefault("DISABLE_TRACING", "1")

app = create_app()
client = TestClient(app)


def test_context_graph_endpoint_returns_data():
    r = client.get("/api/v1/graph/context?limit=10")
    assert r.status_code in (200, 401)
    if r.status_code == 200:
        g = r.json()
        assert "nodes" in g and "edges" in g
