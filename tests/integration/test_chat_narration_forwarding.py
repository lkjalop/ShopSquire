"""Async-narration handoff: /chat/query must forward the recommend layer's llm_summary_job_id (and a
summary_pending flag) so the storefront can poll /api/v1/recommend/narration/{job_id} and replace the
deterministic answer with the richer LLM prose in place. Without this the async narration is dropped."""
from fastapi.testclient import TestClient

from src.app.main import create_app


class _FakeResp:
    def __init__(self, body: dict, status_code: int = 200):
        self._body = body
        self.status_code = status_code

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"http_{self.status_code}")


class _FakeNarrationAsyncClient:
    """Upstream recommend returned the deterministic answer NOW + a job id for the async LLM prose."""
    def __init__(self, timeout: float = 8.0):
        self.timeout = timeout

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url, params=None, headers=None):
        return _FakeResp({
            "results": [{"sku": "GAM-0002", "name": "MSI Katana", "price_cents": 149900,
                         "specs": {"ram_gb": 16}, "factors": {"positive": ["+within_budget"]},
                         "score_norm": 90.0}],
            "assistant_message": "Deterministic grounded answer shown immediately.",
            "decision_trace_id": "trace-narr-1",
            "llm_summary_job_id": "job-narr-abc123",
            "summary_pending": True,
            "next_questions": [],
        })


def test_chat_query_forwards_narration_job_id(monkeypatch):
    from src.app.routers import chat as chat_router

    monkeypatch.setattr(chat_router.httpx, "AsyncClient", _FakeNarrationAsyncClient)
    app = create_app()
    client = TestClient(app)
    resp = client.post(
        "/api/v1/chat/query",
        json={"uid": "u-chat-narr-1", "query": "10 work laptops $1300-$1500"},
        headers={"x-api-key": "local-merchant-key"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("llm_summary_job_id") == "job-narr-abc123"
    assert body.get("summary_pending") is True
