import pytest

from src.app.services.agent_run_replay import (
    ModelReplayEnvelope,
    RecordedToolResult,
    replay_recorded_run,
)
from src.app.services.model_execution_gateway import AgentRunEventLedger, sha256_text
from tests.services.test_model_execution_gateway import _deployment, _request


def _tool(**changes):
    values = {
        "tool_call_id": "tool-1", "tool_name": "official_source_read",
        "input_hash": sha256_text("input"), "output_hash": sha256_text("output"),
        "observed_at": "2026-08-16T10:00:00Z",
        "effective_at": "2026-08-01T00:00:00Z",
        "sanitized_result": {"claim_ids": ["c1"]},
    }
    values.update(changes)
    return RecordedToolResult.model_validate(values)


def test_replay_uses_recorded_results_and_has_no_effect_executor():
    output = "bounded explanation"
    envelope = ModelReplayEnvelope(
        original_request=_request(), recorded_tool_results=[_tool()],
        recorded_output=output, recorded_output_hash=sha256_text(output),
        replay_as_of="2026-08-16T11:00:00Z",
    )
    ledger = AgentRunEventLedger()

    result = replay_recorded_run(envelope, _deployment(), ledger)

    assert result.text == output
    event = ledger.events_for(result.run_id, tenant_id="tenant-a")[-1]
    assert event.event_type == "replayed"
    assert event.details["side_effects_executed"] == 0


def test_future_tool_evidence_cannot_leak_into_replay():
    with pytest.raises(ValueError, match="future_tool_result_in_replay"):
        ModelReplayEnvelope(
            original_request=_request(),
            recorded_tool_results=[_tool(observed_at="2026-08-17T00:00:00Z")],
            recorded_output="x", recorded_output_hash=sha256_text("x"),
            replay_as_of="2026-08-16T00:00:00Z",
        )


def test_replay_rejects_commerce_tool_record():
    with pytest.raises(ValueError, match="commerce_effect_cannot_be_replayed"):
        _tool(tool_name="rfq_send")
