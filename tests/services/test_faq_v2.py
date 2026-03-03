from src.app.services.faq_v2 import semantic_match_faq


def test_faq_v2_buyer_returns_query():
    item, score, intent = semantic_match_faq("my screen is broken, how do i do a warranty return?", role="buyer")
    assert item is not None
    assert intent == "returns_warranty"
    assert score > 0.1
    assert "return" in str(item.get("a") or "").lower() or "warranty" in str(item.get("a") or "").lower()


def test_faq_v2_admin_policy_overlay():
    item, score, intent = semantic_match_faq("show dashboard approval rate and margins", role="admin")
    assert item is not None
    assert intent == "admin_analytics"
    assert score >= 0.0
    assert "admin bi" in str(item.get("a") or "").lower() or "decision replay" in str(item.get("a") or "").lower()

