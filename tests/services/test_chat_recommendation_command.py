from src.app.services.chat_recommendation_dispatch import (
    ChatRecommendationCommand,
    normalize_chat_recommendation_result,
)


def test_chat_command_coerces_boundary_values_once():
    command = ChatRecommendationCommand.from_params({
        "query": 123,
        "uid": "buyer-1",
        "trace_id": "trace-1",
        "turn_intent": "search",
        "external_research_consent": "TRUE",
        "memory_mode": "temporary",
        "session_epoch": " epoch-1 ",
    })

    assert command.query == "123"
    assert command.trace_id == "trace-1"
    assert command.observed_lane == "SEARCH"
    assert command.external_research_consent is True
    assert command.memory_enabled is False
    assert command.session_epoch == "epoch-1"


def test_chat_command_generates_one_trace_identity_when_absent():
    command = ChatRecommendationCommand.from_params({"query": "laptop", "uid": "b"})
    assert command.trace_id
    assert command.raw_params.get("trace_id") is None


def test_dispatch_result_normalization_preserves_authoritative_values():
    command = ChatRecommendationCommand.from_params({
        "query": "laptop", "uid": "b", "trace_id": "trace-1",
        "turn_intent": "research",
    })

    result = normalize_chat_recommendation_result(
        {"execution_mode": "v2_served", "trace_id": "authoritative"},
        command=command,
    )

    assert result == {
        "execution_mode": "v2_served",
        "trace_id": "authoritative",
        "execution_lane": "RESEARCH",
    }
