from src.app.services.trace_taxonomy import normalize_trace_event_type


def test_normalize_known_event():
    ev, orig = normalize_trace_event_type("policy_verdict")
    assert ev == "policy_verdict"
    assert orig is None


def test_normalize_alias_and_unknown():
    ev1, orig1 = normalize_trace_event_type("cv_playbook")
    assert ev1 == "proposal_build"
    assert orig1 is None

    ev2, orig2 = normalize_trace_event_type("custom_weird_event")
    assert ev2 == "feedback_loop"
    assert orig2 == "custom_weird_event"
