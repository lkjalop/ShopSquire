from fastapi.testclient import TestClient

from src.app.main import create_app
from tests.utils import default_headers


app = create_app()
client = TestClient(app)


def test_cv_analyze_async_queue_mode(monkeypatch):
    monkeypatch.setenv("CV_ASYNC_QUEUE_ENABLED", "1")

    from src.app.workers import rq_queue

    monkeypatch.setattr(rq_queue, "enqueue_cv", lambda payload: "job-cv-123", raising=True)
    body = {"case_id": "c1", "labels": ["scratch"], "extracted_text": "minor", "images": []}
    r = client.post("/api/v1/cv/analyze", json=body, headers=default_headers())
    assert r.status_code == 200
    data = r.json()
    assert data.get("status") == "accepted"
    assert data.get("queued") is True
    assert data.get("job_id") == "job-cv-123"
