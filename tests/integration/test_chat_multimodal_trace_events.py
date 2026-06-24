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
                        "sku": "IMG-1",
                        "name": "Visual Match Laptop",
                        "price_cents": 149900,
                        "currency": "USD",
                        "specs": {"ram_gb": 16, "gpu": "RTX 4060"},
                        "factors": {"positive": ["+embedding_similarity", "+within_budget"]},
                        "score_norm": 88.0,
                        "stock_status": "in_stock",
                        "cart_eligible": True,
                    }
                ],
                "assistant_message": "Found 1 visual match.",
                "decision_trace_id": "trace-chat-mm-1",
                "next_questions": [],
            },
            status_code=200,
        )


def test_chat_with_image_emits_multimodal_and_intent_routing_events(monkeypatch):
    from src.app.routers import chat as chat_router

    monkeypatch.setattr(chat_router.httpx, "AsyncClient", _FakeAsyncClient)
    monkeypatch.setattr(
        chat_router,
        "classify_image_intent",
        lambda **kwargs: {
            "intent": "visual_search",
            "confidence": 0.91,
            "reason": "product_photo_detected",
            "signals": {"is_product_photo": True},
            "scores": {"visual_search": 0.91, "cv_triage": 0.09},
        },
    )

    app = create_app()
    client = TestClient(app)
    headers = {"x-api-key": "local-merchant-key"}
    resp = client.post(
        "/api/v1/chat/query",
        json={
            "uid": "u-chat-mm-1",
            "query": "find similar laptops to this photo",
            "images": [
                {
                    "labels": ["laptop", "gaming"],
                    "ocr_text": "Legion",
                    "hash": "img-hash-1",
                    "is_product_photo": True,
                    "damage_score": 0.02,
                }
            ],
        },
        headers=headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    trace_id = body.get("decision_trace_id") or body.get("trace_id")
    assert trace_id == "trace-chat-mm-1"
    product = (body.get("products") or [])[0]
    assert product["price"] == 1499.0
    assert product["price_cents"] == 149900
    assert product["specs"]["gpu"] == "RTX 4060"
    assert product["stock_status"] == "in_stock"
    assert product["cart_eligible"] is True
    assert "+embedding_similarity" in product["why"]

    ev = client.get(f"/api/v1/trace/{trace_id}/events", headers=headers)
    assert ev.status_code == 200
    events = ev.json().get("events") or []
    sources = {str(e.get("source_id") or "") for e in events}
    assert "ImageIntentRouter" in sources
    assert "Chat_Multimodal" in sources
