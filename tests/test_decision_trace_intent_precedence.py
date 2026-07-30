from src.app.routers.decisions import _trace_context_from_events


def test_finalized_recommendation_intent_supersedes_early_observation():
    context = _trace_context_from_events(
        "trace-policy",
        [
            {
                "event_type": "shopper_intent",
                "payload": {"shopper_intent": {"lane": "SEARCH"}},
            },
            {
                "event_type": "feedback_loop",
                "payload": {
                    "_original_event_type": "recommendation_result",
                    "intent_analysis": {
                        "lane": "POLICY_QUESTION",
                        "intent": "POLICY_QUESTION",
                    }
                },
            },
        ],
    )

    assert context["intent_analysis"]["lane"] == "POLICY_QUESTION"
    assert context["_intent_authoritative"] is True


def test_observational_intent_remains_available_without_final_result():
    context = _trace_context_from_events(
        "trace-search",
        [
            {
                "event_type": "shopper_intent",
                "payload": {"shopper_intent": {"lane": "SEARCH"}},
            }
        ],
    )

    assert context["intent_analysis"]["lane"] == "SEARCH"
    assert context["_intent_authoritative"] is False


def test_finalized_facade_route_supersedes_ingress_hint():
    context = _trace_context_from_events(
        "trace-policy-fast-path",
        [
            {
                "event_type": "intent_classify",
                "payload": {"shopper_intent": {"lane": "SEARCH"}},
            },
            {
                "event_type": "intent_classify",
                "source_id": "V2_Recommendation_Facade",
                "payload": {
                    "intent_analysis": {
                        "lane": "POLICY_QUESTION",
                        "intent": "POLICY_QUESTION",
                        "source": "typed_facade_result",
                    },
                    "intent_authority": "finalized_route",
                },
            },
        ],
    )

    assert context["intent_analysis"]["lane"] == "POLICY_QUESTION"
    assert context["_intent_authoritative"] is True
