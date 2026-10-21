from tests.legacy_endpoint_runtime import endpoint_runtime


def test_admin_overview_returns_series(endpoint_runtime):
    _, client = endpoint_runtime
    r = client.get("/api/v1/admin/overview")
    assert r.status_code == 200
    data = r.json()
    assert "decision_series" in data
    assert isinstance(data.get("decision_series"), list)
