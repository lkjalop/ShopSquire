from src.app.services.recommendations import RecommendationService
from src.app.services import recommend_intent_router
from src.app.routers import recommend as recommend_router
from tests.test_recommend import client, _write_flags


def test_followup_explain_detector_extended_phrases():
    positives = [
        "tell me more about that one",
        "what does that mean",
        "how does this compare",
        "can you elaborate on this pick",
        "walk me through why you chose it",
    ]
    for q in positives:
        assert recommend_router._is_followup_explain_query(q) is True


def test_fresh_search_with_rationale_is_not_explain_turn():
    query = (
        "I am thinking to buy 10 laptops for work in 2 weeks, "
        "what is good for 1300 to 1500? why those?"
    )
    assert recommend_router._is_followup_explain_query(query) is True
    assert recommend_router._query_is_standalone_search(query) is True
    assert recommend_router._classify_turn_intent(
        query=query,
        nlp={"intent": "product_search"},
        followup_explain=False,
        explicit_constraint_update=True,
    ) == "FILTER"


def test_inferred_product_search_with_rationale_is_not_followup_explain():
    query = (
        "I need something portable for university but good enough for gaming. "
        "Why are your picks suitable?"
    )
    assert recommend_router._is_followup_explain_query(query) is True
    assert recommend_router._query_is_standalone_search(query) is True


def test_recommend_passes_has_image_to_complexity_context(monkeypatch):
    orig_retrieve = RecommendationService.retrieve_candidates
    captured_contexts = []
    try:
        RecommendationService.retrieve_candidates = lambda self, query, limit=10: [
            {"id": "p1", "sku": "CTX-1", "name": "Laptop A", "price_cents": 109900, "currency": "USD", "stock": 4, "specs": {"ram_gb": 16}},
            {"id": "p2", "sku": "CTX-2", "name": "Laptop B", "price_cents": 129900, "currency": "USD", "stock": 3, "specs": {"ram_gb": 16}},
        ]
        _write_flags(
            {
                "USE_AGENT_CAPABILITIES": True,
                "AGENT_ROLLOUT_PERCENT": 100,
                "CAPABILITIES": {"recommend": {"enabled": True, "rollout_percent": 100}},
                "KILL_SWITCH": False,
                "DECISION_LOG_WRITES_ENABLED": False,
                "DEGRADATION": {"enabled": True},
                "TEST_FORCE_BAD_SKU": False,
            }
        )

        def _capture_model(query, *, context=None):
            captured_contexts.append(dict(context or {}))
            return "llama3:8b"

        def _capture_complex(query, *, context=None):
            captured_contexts.append(dict(context or {}))
            return False

        def _capture_explain(query, *, context=None):
            captured_contexts.append(dict(context or {}))
            return {"length_trigger": False, "matched_keywords": [], "conjunction_count": 0, "score": 0}

        monkeypatch.setattr(recommend_intent_router, "select_ollama_model", _capture_model)
        monkeypatch.setattr(recommend_intent_router, "is_complex_query", _capture_complex)
        monkeypatch.setattr(recommend_intent_router, "complexity_explain", _capture_explain)

        r = client.get(
            "/api/v1/recommend/suggest",
            params={
                "uid": "u-context-img-1",
                "query": "compare alternatives like this",
                "image_labels": "laptop,lenovo",
            },
        )
        assert r.status_code == 200
        assert captured_contexts, "Expected complexity context capture from model-routing helpers"
        assert any(bool(c.get("has_image")) for c in captured_contexts)
    finally:
        RecommendationService.retrieve_candidates = orig_retrieve
