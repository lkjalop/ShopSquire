"""Typed coordinators for the recommendation pipeline's behavior-preserving strangler."""
from __future__ import annotations

from dataclasses import dataclass
from src.app.compat import StrEnum
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
    stage_id: str | None = None
    input_artifact_refs: tuple[str, ...] = ()
    output_artifact_refs: tuple[str, ...] = ()
    dependency_stage_ids: tuple[str, ...] = ()
    isolated: bool = False


_PHASE_ORDER = {
    phase: index for index, phase in enumerate((
        RecommendationPhase.INTERPRETATION,
        RecommendationPhase.EVIDENCE,
        RecommendationPhase.FIT,
        RecommendationPhase.COMMERCIAL,
        RecommendationPhase.RESPONSE,
    ))
}


def validate_stage_order(stages: Iterable[CoordinatedStage]) -> tuple[CoordinatedStage, ...]:
    """Freeze the strangler order before any stage is allowed to execute."""
    frozen = tuple(stages)
    positions = [_PHASE_ORDER[stage.phase] for stage in frozen]
    if positions != sorted(positions):
        raise ValueError("recommendation_stage_order_invalid")
    seen = set()
    for stage in frozen:
        identity = stage.stage_id or stage.name
        if identity in seen:
            raise ValueError('recommendation_stage_id_duplicate')
        if any(dependency not in seen for dependency in stage.dependency_stage_ids):
            raise ValueError('recommendation_stage_dependency_missing_or_forward')
        seen.add(identity)
    return frozen


def run_coordinated_stages(
    response: Any,
    stages: Iterable[CoordinatedStage],
    *,
    cancellation: Any = None,
    logger: Any = None,
) -> None:
    """Run ordered typed stages through the canonical failure/cancellation guard."""
    statuses = {}
    for stage in validate_stage_order(stages):
        identity = stage.stage_id or stage.name
        if any(statuses[dependency] != 'ok' for dependency in stage.dependency_stage_ids):
            statuses[identity] = 'blocked'
            response.record_stage(stage.name, status='blocked', stage_id=stage.stage_id,
                                  dependency_stage_ids=stage.dependency_stage_ids)
            continue
        statuses[identity] = run_guarded_stage(
            response,
            stage.name,
            stage.operation,
            cancellation=cancellation,
            logger=logger,
            input_artifact_refs=stage.input_artifact_refs,
            output_artifact_refs=stage.output_artifact_refs,
            dependency_stage_ids=stage.dependency_stage_ids,
            stage_id=stage.stage_id,
            isolated=stage.isolated,
        )


__all__ = [
    "CoordinatedStage", "RecommendationPhase", "run_coordinated_stages",
    "validate_stage_order",
]
