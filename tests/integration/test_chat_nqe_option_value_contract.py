from fastapi.testclient import TestClient

from src.app.main import create_app


_SEEN_PARAMS = {}


async def _fake_recommend(request, params, **kwargs):
    _SEEN_PARAMS.clear()
    _SEEN_PARAMS.update(params or {})
    return 200, {
        "results": [],
        "assistant_message": "ok",
        "decision_trace_id": "trace-chat-nqe-1",
        "next_questions": [],
    }


def test_chat_nqe_option_value_is_forwarded_to_recommend(monkeypatch):
    from src.app.routers import chat as chat_router

    monkeypatch.setattr(chat_router, "_call_recommend_in_process", _fake_recommend)
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
    assert _SEEN_PARAMS.get("nqe_question_id") == "ask_budget"
    assert _SEEN_PARAMS.get("nqe_option_id") == "budget_1500_2200"
    assert _SEEN_PARAMS.get("nqe_option_label") == "$1,500-$2,200"
    assert _SEEN_PARAMS.get("nqe_option_value") == "1500-2200"


def test_chat_forwards_qr_cv_signals_from_image_security_payload(monkeypatch):
    from src.app.routers import chat as chat_router

    monkeypatch.setattr(chat_router, "_call_recommend_in_process", _fake_recommend)
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
    raw = str(_SEEN_PARAMS.get("image_cv_signals") or "")
    assert '"qr_code_detected":true' in raw
    assert '"qr_external_url_detected":true' in raw
    assert '"qr_prompt_injection":true' in raw
