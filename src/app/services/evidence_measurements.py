"""Typed values for evidence that may be missing, withheld, stale, or censored.

Zero is a value.  It is never a substitute for an observation that was not
collected or a supplier field that was not disclosed.  This contract is
vertical-agnostic and deliberately carries no ranking or commerce authority.
"""
from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class MeasurementState(StrEnum):
    OBSERVED = "observed"
    ATTESTED = "attested"
    DERIVED = "derived"
    INFERRED = "inferred"
    NOT_COLLECTED = "not_collected"
    NOT_DISCLOSED = "not_disclosed"
    NOT_APPLICABLE = "not_applicable"
    RIGHT_CENSORED = "right_censored"
    STALE = "stale"
    CONTRADICTED = "contradicted"
    UNKNOWN = "unknown"


_VALUE_STATES = {
    MeasurementState.OBSERVED,
    MeasurementState.ATTESTED,
    MeasurementState.DERIVED,
    MeasurementState.INFERRED,
    MeasurementState.STALE,
    MeasurementState.CONTRADICTED,
}


class EvidenceMeasurement(BaseModel):
    """One unit-bearing value plus its observation and disclosure truth."""

    model_config = ConfigDict(extra="forbid")

    metric: str = Field(min_length=1, max_length=120)
    state: MeasurementState
    value: float | int | str | bool | None = None
    unit: str | None = Field(default=None, max_length=40)
    numerator: int | None = Field(default=None, ge=0)
    denominator: int | None = Field(default=None, ge=0)
    observed_at: str | None = None
    source_authority: str = Field(default="unspecified", max_length=160)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    reason: str | None = Field(default=None, max_length=300)
    provenance_chain: list[str] = Field(default_factory=list, max_length=32)
    authority: Literal["evidence_only"] = "evidence_only"

    @model_validator(mode="after")
    def validate_value_state(self) -> "EvidenceMeasurement":
        if self.state in _VALUE_STATES and self.value is None:
            raise ValueError("measurement_value_required")
        if self.state not in _VALUE_STATES and self.value is not None:
            raise ValueError("missing_measurement_cannot_have_value")
        if self.numerator is not None or self.denominator is not None:
            if self.numerator is None or self.denominator is None:
                raise ValueError("rate_counts_must_be_paired")
            if self.numerator > self.denominator:
                raise ValueError("rate_numerator_exceeds_denominator")
        return self


def missing_measurement(metric: str, state: MeasurementState, *, reason: str) -> EvidenceMeasurement:
    if state in _VALUE_STATES:
        raise ValueError("missing_measurement_requires_non_value_state")
    return EvidenceMeasurement(metric=metric, state=state, reason=reason)


__all__ = ["EvidenceMeasurement", "MeasurementState", "missing_measurement"]
