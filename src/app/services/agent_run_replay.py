"""Side-effect-free replay of a recorded model run."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.app.services.model_execution_gateway import (
    AgentRunEventLedger,
    ModelDeployment,
    ModelExecutionRequest,
    ModelExecutionResult,
    sha256_text,
)


_PROHIBITED_EFFECTS = frozenset({
    "rfq_send", "cart_mutation", "payment", "shipment", "supplier_email_send",
})


class RecordedToolResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_call_id: str = Field(min_length=1, max_length=160)
    tool_name: str = Field(min_length=1, max_length=160)
    input_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    output_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    observed_at: str
    effective_at: str
    sanitized_result: dict[str, Any]

    @model_validator(mode="after")
    def prohibit_effect_tools(self) -> "RecordedToolResult":
        if self.tool_name in _PROHIBITED_EFFECTS:
            raise ValueError("commerce_effect_cannot_be_replayed")
        return self


class ModelReplayEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    original_request: ModelExecutionRequest
    recorded_tool_results: list[RecordedToolResult] = Field(default_factory=list, max_length=64)
    recorded_output: str = Field(max_length=20_000)
    recorded_output_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    replay_as_of: str
    effects_allowed: Literal[False] = False

    @model_validator(mode="after")
    def validate_output_hash(self) -> "ModelReplayEnvelope":
        if sha256_text(self.recorded_output) != self.recorded_output_hash:
            raise ValueError("recorded_output_hash_mismatch")
        if any(row.observed_at > self.replay_as_of for row in self.recorded_tool_results):
            raise ValueError("future_tool_result_in_replay")
        return self


def replay_recorded_run(
    envelope: ModelReplayEnvelope,
    deployment: ModelDeployment,
    ledger: AgentRunEventLedger,
) -> ModelExecutionResult:
    """Return recorded output; deliberately accepts no transport or tool executor."""

    request = envelope.original_request
    if request.deployment_id != deployment.deployment_id:
        raise ValueError("replay_deployment_identity_mismatch")
    ledger.append(
        request, deployment, "replayed", replay_as_of=envelope.replay_as_of,
        recorded_tool_result_count=len(envelope.recorded_tool_results),
        output_hash=envelope.recorded_output_hash, side_effects_executed=0,
    )
    return ModelExecutionResult(
        status="completed", run_id=request.run_id, text=envelope.recorded_output,
        output_hash=envelope.recorded_output_hash, elapsed_ms=0, failure_code=None,
        late_result_quarantined=False, dlp_hits=0,
    )


__all__ = ["ModelReplayEnvelope", "RecordedToolResult", "replay_recorded_run"]
