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


class _FakeAsyncClient:
    def __init__(self, timeout: float = 8.0):
        self.timeout = timeout

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url, params=None, headers=None):
        return _FakeResp(
            {
                "results": [
                    {
                        "sku": "HIST-1",
                        "name": "History Laptop",
                        "price_cents": 99900,
                        "specs": {"ram_gb": 16},
                        "factors": {"positive": ["+within_budget"]},
                        "score_norm": 82.0,
                    }
                ],
                "assistant_message": "Found 1 match.",
                "decision_trace_id": "trace-chat-history-1",
                "next_questions": [],
            },
            status_code=200,
        )


def test_chat_query_persists_messages_and_history_reads(monkeypatch):
    from src.app.routers import chat as chat_router

    monkeypatch.setattr(chat_router.httpx, "AsyncClient", _FakeAsyncClient)
    app = create_app()
    client = TestClient(app)
    headers = {"x-api-key": "local-merchant-key"}

    resp = client.post(
        "/api/v1/chat/query",
        json={"uid": "u-chat-history-1", "query": "show me laptops under 1000"},
        headers=headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert (body.get("decision_trace_id") or body.get("trace_id")) == "trace-chat-history-1"

    hist = client.get(
        "/api/v1/chat/history",
        params={"uid": "u-chat-history-1", "limit": 10},
        headers=headers,
    )
    assert hist.status_code == 200
    h = hist.json()
    items = h.get("items") or []
    assert len(items) >= 2
    roles = [str((x or {}).get("role") or "") for x in items]
    assert "user" in roles
    assert "assistant" in roles


def test_chat_query_applies_copywriting_when_requested(monkeypatch):
    from src.app.routers import chat as chat_router

    monkeypatch.setattr(chat_router.httpx, "AsyncClient", _FakeAsyncClient)
    app = create_app()
    client = TestClient(app)
    headers = {"x-api-key": "local-merchant-key"}

    resp = client.post(
        "/api/v1/chat/query",
        json={
            "uid": "u-chat-copy-1",
            "query": "show me laptops under 1000",
            "copywriting_enabled": True,
            "copy_profile_id": "premium",
            "brand_name": "Acme",
            "copy_surface": "storefront",
        },
        headers=headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assistant = str(body.get("assistant_message") or "")
    assert "Acme:" in assistant
    copy_meta = body.get("copywriting") or {}
    assert bool(copy_meta.get("applied")) is True
    assert copy_meta.get("profile_id") == "premium"
    assert copy_meta.get("cpu_cost") == "low"
