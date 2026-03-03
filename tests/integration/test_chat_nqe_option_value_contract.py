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
    seen_params = {}

    def __init__(self, timeout: float = 8.0):
        self.timeout = timeout

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url, params=None, headers=None):
        _FakeAsyncClient.seen_params = dict(params or {})
        return _FakeResp(
            {
                "results": [],
                "assistant_message": "ok",
                "decision_trace_id": "trace-chat-nqe-1",
                "next_questions": [],
            },
            status_code=200,
        )


def test_chat_nqe_option_value_is_forwarded_to_recommend(monkeypatch):
    from src.app.routers import chat as chat_router

    monkeypatch.setattr(chat_router.httpx, "AsyncClient", _FakeAsyncClient)
    app = create_app()
    client = TestClient(app)
    headers = {"x-api-key": "local-merchant-key"}
    resp = client.post(
        "/api/v1/chat/query",
        json={
            "uid": "u-chat-nqe-ov-1",
            "query": "show laptops",
            "nqe_selection": {
                "question_id": "ask_budget",
                "option_id": "budget_1500_2200",
                "option_label": "$1,500-$2,200",
                "option_value": "1500-2200",
            },
        },
        headers=headers,
    )
    assert resp.status_code == 200
    assert _FakeAsyncClient.seen_params.get("nqe_question_id") == "ask_budget"
    assert _FakeAsyncClient.seen_params.get("nqe_option_id") == "budget_1500_2200"
    assert _FakeAsyncClient.seen_params.get("nqe_option_label") == "$1,500-$2,200"
    assert _FakeAsyncClient.seen_params.get("nqe_option_value") == "1500-2200"


def test_chat_forwards_qr_cv_signals_from_image_security_payload(monkeypatch):
    from src.app.routers import chat as chat_router

    monkeypatch.setattr(chat_router.httpx, "AsyncClient", _FakeAsyncClient)
    app = create_app()
    client = TestClient(app)
    headers = {"x-api-key": "local-merchant-key"}
    resp = client.post(
        "/api/v1/chat/query",
        json={
            "uid": "u-chat-cv-signal-1",
            "query": "find similar laptops",
            "images": [
                {
                    "labels": ["laptop"],
                    "security": {
                        "cv_signals": {
                            "qr_url_present": True,
                            "prompt_injection_text_suspected": True,
                            "adversarial_score": 0.62,
                        }
                    },
                    "reasons": ["qr_code_detected", "qr_external_url_detected"],
                }
            ],
        },
        headers=headers,
    )
    assert resp.status_code == 200
    raw = str(_FakeAsyncClient.seen_params.get("image_cv_signals") or "")
    assert '"qr_code_detected":true' in raw
    assert '"qr_external_url_detected":true' in raw
    assert '"qr_prompt_injection":true' in raw
