import threading
from fastapi.testclient import TestClient
from src.app.main import create_app


def test_concurrency_backpressure_returns_503(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///test.sqlite")
    monkeypatch.setenv("DISABLE_TRACING", "1")
    monkeypatch.setenv("MAX_CONCURRENCY", "1")
    app = create_app()
    client = TestClient(app)

    def _do_request(results: list):
        r = client.get("/api/v1/admin/overview", headers={"x-api-key": "local-developer-key"})
        results.append(r.status_code)

    results = []
    t1 = threading.Thread(target=_do_request, args=(results,))
    t2 = threading.Thread(target=_do_request, args=(results,))
    t1.start(); t2.start()
    t1.join(); t2.join()
    # Expect one success and one 503 busy
    assert 503 in results
    assert 200 in results or 404 in results or 400 in results or 422 in results
