from src.app.routers import decisions
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


def test_canonical_trace_overlays_finalized_event_intent(monkeypatch):
    row = {
        "id": "trace-policy-canonical",
        "agent_name": "Recommendation_Core",
        "valid_from": "2026-07-30T00:00:00Z",
        "valid_to": None,
        "system_from": "2026-07-30T00:00:00Z",
        "system_to": None,
        "input_data": {"intent": {"lane": "SEARCH"}},
        "retrieved_context": {},
        "proposed_action": {},
        "execution_status": "completed",
    }

    class _Mappings:
        def first(self):
            return row

    class _Result:
        def mappings(self):
            return _Mappings()

    class _Db:
        def execute(self, *_args, **_kwargs):
            return _Result()

    monkeypatch.setattr(decisions, "_decision_reads_enabled", lambda _flags: True)
    monkeypatch.setattr(decisions, "_ff_get_flags", lambda: {})
    monkeypatch.setattr(
        decisions,
        "_fetch_trace_events",
        lambda _trace_id: [
            {
                "event_type": "intent_classify",
                "payload": {
                    "intent_analysis": {
                        "lane": "POLICY_QUESTION",
                        "intent": "POLICY_QUESTION",
                    },
                    "intent_authority": "finalized_route",
                },
            }
        ],
    )

    trace = decisions.get_decision_trace(
        "trace-policy-canonical",
        role="owner",
        db=_Db(),
    )

    assert trace["intent_analysis"]["lane"] == "POLICY_QUESTION"
