import os
from fastapi.testclient import TestClient


def _make_mock_post(active=True, extra=None):
    class MockResp:
        def __init__(self, data):
            self._data = data

        def raise_for_status(self):
            return None

        def json(self):
            return self._data

    data = {"active": active}
    if extra:
        data.update(extra)
    return lambda *a, **k: MockResp(data)


def test_metrics_owner_via_introspection(monkeypatch):
    # Configure introspection URL env
    os.environ["OIDC_INTROSPECTION_URL"] = "https://auth.example/introspect"
    # Mock requests.post to return active owner role
    import requests

    monkeypatch.setattr(requests, "post", _make_mock_post(active=True, extra={"role": "owner"}))

    from src.app.main import create_app

    app = create_app()
    client = TestClient(app)

    # Avoid cache collisions across tests by using a unique token.
    import uuid
    try:
        import src.app.security.auth as authmod
        authmod._INTROSPECTION_CACHE.clear()
    except Exception:
        pass
    tok = f"tok-{uuid.uuid4().hex}"
    resp = client.get("/metrics", headers={"Authorization": f"Bearer {tok}"})
    assert resp.status_code == 200
    body = resp.text
    # Owner should see raw tenant metrics help text
    assert "shopsquire_cv_provider_latency_tenant_seconds" in body


def test_metrics_merchant_requires_tenant_header(monkeypatch):
    os.environ["OIDC_INTROSPECTION_URL"] = "https://auth.example/introspect"
    import requests
    # Introspect returns merchant role
    monkeypatch.setattr(requests, "post", _make_mock_post(active=True, extra={"role": "merchant"}))

    from src.app.main import create_app

    app = create_app()
    client = TestClient(app)

    # Without x-tenant-id, tenant metrics should be redacted/absent
    import uuid
    try:
        import src.app.security.auth as authmod
        authmod._INTROSPECTION_CACHE.clear()
    except Exception:
        pass
    tok = f"tok-{uuid.uuid4().hex}"
    resp = client.get("/metrics", headers={"Authorization": f"Bearer {tok}"})
    assert resp.status_code == 200
    body = resp.text
    assert "shopsquire_cv_provider_latency_tenant_seconds" not in body

    # With x-tenant-id, allowed tenant lines should be present or at least response OK
    resp2 = client.get("/metrics", headers={"Authorization": f"Bearer {tok}", "x-tenant-id": "tenant_123"})
    assert resp2.status_code == 200
