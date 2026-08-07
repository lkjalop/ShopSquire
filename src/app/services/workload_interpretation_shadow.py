"""Observation-only comparison of canonical and legacy workload interpretation.

This module exists to measure whether the model-plus-registry interpretation can
replace the older title lists and query decomposer.  Its result is diagnostic:
callers must never use it to route, retrieve, rank, or authorize a product.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
import re
from typing import Any, Callable, Iterable, Mapping, Sequence


DecomposeFn = Callable[[str], Any]
DetectFn = Callable[[str], Sequence[str]]


def shadow_enabled() -> bool:
    return str(os.getenv("WORKLOAD_INTERPRETATION_SHADOW_ENABLED", "0")).strip().lower() in {
        "1", "true", "yes", "on",
    }


def _key(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")


def _keys(values: Iterable[object]) -> tuple[str, ...]:
    return tuple(sorted({item for value in values if (item := _key(value))}))


@dataclass(frozen=True)
class WorkloadInterpretationShadow:
    status: str
    canonical_entities: tuple[str, ...]
    canonical_use_cases: tuple[str, ...]
    legacy_entities: tuple[str, ...]
    legacy_use_cases: tuple[str, ...]
    divergence_codes: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "mode": "observer",
            "status": self.status,
            "canonical": {
                "entities": list(self.canonical_entities),
                "use_cases": list(self.canonical_use_cases),
            },
            "legacy": {
                "entities": list(self.legacy_entities),
                "use_cases": list(self.legacy_use_cases),
            },
            "divergence_codes": list(self.divergence_codes),
            "authoritative": False,
        }


def compare_workload_interpretations(
    query: str,
    *,
    canonical_entities: Sequence[tuple[str, str]] = (),
    canonical_use_cases: Sequence[str] = (),
    decompose_fn: DecomposeFn | None = None,
    detect_games_fn: DetectFn | None = None,
    detect_software_fn: DetectFn | None = None,
) -> WorkloadInterpretationShadow:
    """Compare interpretations without promoting legacy output to evidence."""

    canonical_entity_keys = _keys(name for _kind, name in canonical_entities)
    canonical_use_case_keys = _keys(canonical_use_cases)

    if decompose_fn is None or detect_games_fn is None or detect_software_fn is None:
        from src.app.flows.nqe import detect_games_in_text, detect_software_in_text
        from src.app.services.query_decomposer import decompose

        decompose_fn = decompose_fn or decompose
        detect_games_fn = detect_games_fn or detect_games_in_text
        detect_software_fn = detect_software_fn or detect_software_in_text

    legacy_entities = _keys(
        list(detect_games_fn(query)) + list(detect_software_fn(query))
    )
    plan = decompose_fn(query)
    legacy_use_cases = _keys(getattr(plan, "use_cases", ()) or ())

    divergences: list[str] = []
    if set(legacy_entities) - set(canonical_entity_keys):
        divergences.append("legacy_entity_only")
    if set(canonical_entity_keys) - set(legacy_entities):
        divergences.append("canonical_entity_only")
    if set(legacy_use_cases) != set(canonical_use_case_keys):
        divergences.append("use_case_mismatch")

    return WorkloadInterpretationShadow(
        status="equivalent" if not divergences else "divergent",
        canonical_entities=canonical_entity_keys,
        canonical_use_cases=canonical_use_case_keys,
        legacy_entities=legacy_entities,
        legacy_use_cases=legacy_use_cases,
        divergence_codes=tuple(divergences),
    )


def observe_workload_interpretations(
    query: str,
    *,
    canonical_entities: Sequence[tuple[str, str]] = (),
    canonical_use_cases: Sequence[str] = (),
) -> Mapping[str, Any] | None:
    """Run the legacy comparison only under the explicit shadow flag."""

    if not shadow_enabled():
        return None
    return compare_workload_interpretations(
        query,
        canonical_entities=canonical_entities,
        canonical_use_cases=canonical_use_cases,
    ).as_dict()
