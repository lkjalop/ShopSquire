from fastapi.testclient import TestClient
from src.app.main import create_app
import re


def _get_counter_value(metrics_text: str, counter_name: str) -> int:
    # find line like counter_name{...} value or counter_name value
    pattern = r"^" + re.escape(counter_name) + r"(?:\{[^}]*\})?\s+(\d+)"
    m = re.search(pattern, metrics_text, re.M)
    if not m:
        return 0
    return int(m.group(1))


def test_query_cluster_increments_metric():
    app = create_app()
    client = TestClient(app)
    # read metrics before
    r = client.get("/metrics")
    assert r.status_code == 200
    before = _get_counter_value(r.text, "shopsquire_query_cluster_volume_total")

    # call clustering endpoint (include API key header for role guard)
    headers = {"x-api-key": "local-merchant-key"}
    payload = {"queries": ["Where is my order?", "Track shipment"], "min_cluster_size": 1, "persist": False}
    r = client.post("/api/v1/analytics/query_clusters", json=payload, headers=headers)
    assert r.status_code == 200
    # read metrics after
    r2 = client.get("/metrics")
    after = _get_counter_value(r2.text, "shopsquire_query_cluster_volume_total")
    assert after >= before + 1


def test_ragas_summary_endpoint():
    app = create_app()
    client = TestClient(app)
    headers = {"x-api-key": "local-merchant-key"}
    r = client.get("/api/v1/analytics/ragas/summary", headers=headers)
    assert r.status_code == 200
    j = r.json()
    assert "ok" in j
