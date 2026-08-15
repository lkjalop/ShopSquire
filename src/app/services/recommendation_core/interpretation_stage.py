"""Typed interpretation-to-requirement stage extracted from the legacy core."""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import Any, Callable

from src.app.services.recommendation_core.intent_resolver import resolve as resolve_intent
from src.app.services.workload_interpretation_shadow import observe_workload_interpretations


@dataclass(frozen=True)
class InterpretationStageResult:
    decision: Any
    intent: dict[str, Any]
    shadow: dict[str, Any] | None
    dropped_requirement_keys: tuple[str, ...]


def resolve_interpretation_stage(
    decision: Any,
    envelope: Any,
    *,
    vertical: str | None,
    is_workload_host_product: Callable[[str | None], bool],
) -> InterpretationStageResult:
    """Resolve workload requirements without owning retrieval or commerce."""

    stated_keys = set(decision.requirements)
    intent = resolve_intent(
        list(decision.use_cases), dict(decision.requirements), query=envelope.query,
        vertical=vertical, use_case_variants=dict(decision.use_case_variants),
        workload_entities=list(decision.workload_entities),
        external_research_consent=envelope.external_research_consent,
    )
    resolved = dict(intent["requirements"])
    interpreted = dataclasses.replace(
        decision, use_cases=tuple(intent["use_cases"]),
        use_case_variants=dict(intent.get("use_case_variants") or {}),
    )
    shadow = observe_workload_interpretations(
        envelope.query, canonical_entities=interpreted.workload_entities,
        canonical_use_cases=interpreted.use_cases,
    )
    dropped: tuple[str, ...] = ()
    if not is_workload_host_product(interpreted.requested_product_node):
        dropped = tuple(sorted(key for key in resolved if key not in stated_keys))
        resolved = {key: value for key, value in resolved.items() if key in stated_keys}
    interpreted = dataclasses.replace(interpreted, requirements=resolved)
    return InterpretationStageResult(
        decision=interpreted, intent=intent, shadow=shadow,
        dropped_requirement_keys=dropped,
    )


__all__ = ["InterpretationStageResult", "resolve_interpretation_stage"]
