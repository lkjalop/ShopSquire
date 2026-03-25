from src.app.services import faq_v2


def test_semantic_match_faq_prefers_vector_hits(monkeypatch):
    monkeypatch.setattr(
        faq_v2,
        "_try_vector_faq_search",
        lambda query, top_k=3: [
            {
                "q": "How do returns work?",
                "a": "You can submit a return request from your order history.",
                "tags": ["return", "refund"],
                "_distance": 0.2,
            }
        ],
    )

    item, score, intent = faq_v2.semantic_match_faq("I need to send back a broken order", role="buyer")

    assert item is not None
    assert item.get("_source") == "vector"
    assert intent == "returns_warranty"
    assert score >= 0.45
    assert "return" in str(item.get("a") or "").lower()
