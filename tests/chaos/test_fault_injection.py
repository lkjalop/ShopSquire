import os
import random
import time
from fastapi.testclient import TestClient
from src.app.main import create_app


def test_randomized_endpoint_mix_under_faults(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///test.sqlite")
    monkeypatch.setenv("DISABLE_TRACING", "1")
    monkeypatch.setenv("SKIP_OBSERVER_ENDPOINTS", "/api/v1/recommend,/api/v1/admin")
    app = create_app()
    client = TestClient(app)
    headers = {
        "x-api-key": os.getenv("MERCHANT_API_KEY", "local-merchant-key"),
        "x-skip-observer": "1",
    }
    endpoints = [
        ("GET", "/api/v1/admin/overview", {}),
        ("GET", "/api/v1/recommend/suggest", {"query": "laptop"}),
        ("GET", "/api/v1/admin/security/metrics", {}),
    ]
    # Inject transient faults: occasionally send invalid params
    start = time.time()
    for i in range(100):
        method, path, params = random.choice(endpoints)
        # 10% chance to inject bad input
        if random.random() < 0.1 and "query" in params:
            params = {"query": "'" * 50}
        r = client.request(method, path, params=params, headers=headers)
        # Expect robust handling: either 200 OK or a meaningful 4xx without server error
        assert r.status_code in (200, 400, 404, 422)
    # Simple time bound to flag egregious slowdowns
    assert time.time() - start < 15
