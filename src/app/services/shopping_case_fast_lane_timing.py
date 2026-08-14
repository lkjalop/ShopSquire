"""Typed timing projection for zero-network shopping-case interpretation."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ShoppingCaseFastLaneTiming(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["shopping-case-fast-lane-timing-v1"] = (
        "shopping-case-fast-lane-timing-v1"
    )
    catalog_candidate_ms: float = Field(ge=0)
    research_plan_ms: float = Field(ge=0)
    case_persistence_ms: float = Field(ge=0)
    shelf_projection_ms: float = Field(ge=0)
    response_projection_ms: float = Field(ge=0)
    total_ms: float = Field(ge=0)
    deadline_ms: int = Field(default=20_000, ge=100, le=60_000)
    deadline_status: Literal["within_deadline", "deadline_exceeded"]
    external_calls: Literal[0] = 0

    @model_validator(mode="after")
    def validate_status(self) -> "ShoppingCaseFastLaneTiming":
        expected = "within_deadline" if self.total_ms <= self.deadline_ms else "deadline_exceeded"
        if self.deadline_status != expected:
            raise ValueError("shopping_case_fast_lane_deadline_status_mismatch")
        return self


__all__ = ["ShoppingCaseFastLaneTiming"]
