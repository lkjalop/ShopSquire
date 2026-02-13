from fastapi.testclient import TestClient

from src.app.main import create_app
from tests.utils import default_headers


def test_recommend_tenant_quota_blocks_when_limit_exceeded(monkeypatch):
    monkeypatch.setenv("TENANT_QUOTAS_ENABLED", "1")
    monkeypatch.setenv("TENANT_QUOTA_RECOMMEND_CALLS_DAILY", "0")
    app = create_app()
    client = TestClient(app, headers=default_headers())
    r = client.get(
        "/api/v1/recommend/suggest",
        params={"uid": "quota-user", "query": "laptop under $1000"},
        headers={**default_headers(), "x-tenant-id": "tenant-q"},
    )
    assert r.status_code == 429
    body = r.json()
    # fastapi HTTPException wraps payload under detail
    detail = body.get("detail") if isinstance(body, dict) else {}
    assert isinstance(detail, dict)
    assert detail.get("error") == "tenant_quota_exceeded"
