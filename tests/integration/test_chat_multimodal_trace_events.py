from fastapi.testclient import TestClient

from src.app.main import create_app


def _compatibility_image_response(**_kwargs):
    return {
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
            }


def test_chat_with_image_emits_multimodal_and_intent_routing_events(monkeypatch):
    from src.app.routers import chat as chat_router
    from src.app.services import recommendation_compatibility

    # Chat dispatches through the typed facade and V2-only compatibility cutover.
    monkeypatch.setattr(
        recommendation_compatibility,
        "serve_v2_compatibility",
        _compatibility_image_response,
    )
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
    assert "Multimodal_Fusion" in sources


def test_chat_with_voice_emits_multimodal_provenance_without_image(monkeypatch):
    from src.app.routers import chat as chat_router

    async def fake_recommend(*_args, **_kwargs):
        return 200, {
            "results": [{"sku": "VOICE-1", "name": "Voice Match", "price": 999}],
            "assistant_message": "Found one voice match.",
            "decision_trace_id": "trace-chat-voice-1",
            "next_questions": [],
            "execution_mode": "v2_served",
        }

    monkeypatch.setattr(chat_router, "_call_recommend_in_process", fake_recommend)

    client = TestClient(create_app())
    headers = {"x-api-key": "local-merchant-key"}
    response = client.post(
        "/api/v1/chat/query",
        json={
            "uid": "u-chat-voice-1",
            "voice_transcript": "gaming laptop under 2000",
            "voice_confidence": 0.95,
        },
        headers=headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["voice_used"] is True
    trace_id = body.get("decision_trace_id") or body.get("trace_id")
    events_response = client.get(
        f"/api/v1/trace/{trace_id}/events",
        headers=headers,
    )
    assert events_response.status_code == 200
    fusion = [
        event for event in (events_response.json().get("events") or [])
        if (event.get("payload") or {}).get("_original_event_type") == "multimodal_fusion"
    ]
    assert len(fusion) == 1
    assert fusion[0]["source_id"] == "Multimodal_Fusion"
    assert fusion[0]["source_type"] == "stage"
    assert fusion[0]["payload"]["voice_used"] is True
    assert fusion[0]["payload"]["image_count"] == 0
