from src.app.services import recommend_intent_router
from src.app.services.query_classifier import (
    classify_query,
    classify_turn_intent,
    is_fresh_search_request,
    is_followup_explain_query,
    is_standalone_search,
)


def test_followup_explain_detector_extended_phrases():
    positives = [
        "tell me more about that one",
        "what does that mean",
        "how does this compare",
        "can you elaborate on this pick",
        "walk me through why you chose it",
    ]
    for q in positives:
        assert is_followup_explain_query(q) is True


def test_fresh_search_with_rationale_is_not_explain_turn():
    query = (
        "I am thinking to buy 10 laptops for work in 2 weeks, "
        "what is good for 1300 to 1500? why those?"
    )
    assert is_followup_explain_query(query) is True
    assert is_standalone_search(query) is True
    assert classify_turn_intent(
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
    assert is_followup_explain_query(query) is True
    assert is_standalone_search(query) is True
    assert is_fresh_search_request(query) is True
    assert classify_query(query)["turn_intent"] == "SEARCH"


def test_prior_product_rationale_remains_explain():
    query = "Why is this laptop suitable?"
    assert is_followup_explain_query(query) is True
    assert is_fresh_search_request(query) is False
    assert classify_query(query)["turn_intent"] == "EXPLAIN"


def test_recommend_passes_has_image_to_complexity_context(monkeypatch):
    captured_contexts = []

    def _capture_model(query, *, context=None):
        captured_contexts.append(dict(context or {}))
        return "llama3:8b"

    def _capture_complex(query, *, context=None):
        captured_contexts.append(dict(context or {}))
        return False

    def _capture_explain(query, *, context=None):
        captured_contexts.append(dict(context or {}))
        return {
            "length_trigger": False,
            "matched_keywords": [],
            "conjunction_count": 0,
            "score": 0,
        }

    monkeypatch.setattr(recommend_intent_router, "select_ollama_model", _capture_model)
    monkeypatch.setattr(recommend_intent_router, "is_complex_query", _capture_complex)
    monkeypatch.setattr(recommend_intent_router, "complexity_explain", _capture_explain)

    recommend_intent_router.resolve_intent_routing(
        query_effective="compare alternatives like this",
        nlp={"intent": "compare"},
        complexity_context={"has_image": True},
        flags={"OLLAMA_INTENT_ROUTING": {"stage": "off"}},
        uid="u-context-img-1",
        trace_id="trace-context-img-1",
        fast_path_enabled=False,
        log_trace_event=lambda **_event: None,
    )

    assert captured_contexts
    assert all(context.get("has_image") is True for context in captured_contexts)
