from src.app.services.i18n import localize_recommend_payload


def test_localize_clarifying_payload_spanish():
    payload = {
        "status": "clarifying_questions",
        "assistant_message": "fallback",
        "next_questions": [
            {"id": "q1", "text": "What's your budget range?"},
            {"id": "q2", "text": "What will you use it for?"},
            {"id": "q3", "text": "Any brand preference?"},
        ],
    }
    out = localize_recommend_payload(payload, "es")
    assert out.get("locale") == "es"
    assert "presupuesto" in (out.get("next_questions")[0].get("text") or "").lower()
