"""Typed coordinators for the recommendation pipeline's behavior-preserving strangler."""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Callable, Iterable

from src.app.services.recommendation_core.stage_runner import run_guarded_stage


class RecommendationPhase(StrEnum):
    INTERPRETATION = "interpretation"
    EVIDENCE = "evidence"
    FIT = "fit"
    COMMERCIAL = "commercial"
    RESPONSE = "response"


@dataclass(frozen=True)
class CoordinatedStage:
    phase: RecommendationPhase
    name: str
    operation: Callable[[], None]


def run_coordinated_stages(
    response: Any,
    stages: Iterable[CoordinatedStage],
    *,
    cancellation: Any = None,
    logger: Any = None,
) -> None:
    """Run ordered typed stages through the canonical failure/cancellation guard."""
    for stage in stages:
        run_guarded_stage(
            response,
            stage.name,
            stage.operation,
            cancellation=cancellation,
            logger=logger,
        )


__all__ = ["CoordinatedStage", "RecommendationPhase", "run_coordinated_stages"]
