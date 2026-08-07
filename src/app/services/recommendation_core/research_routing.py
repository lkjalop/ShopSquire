"""Shadow-only research trigger assessment.

This observer estimates whether catalog-only retrieval is likely to be insufficient.
It is intentionally uncalibrated and cannot select a lane, authorize research, compile
requirements, or expose products. Logged observations become training/evaluation data
for a later calibrated Query Performance Prediction model.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ResearchTriggerObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    state: Literal["catalog_sufficient", "ambiguous_intent", "unresolved_workload"]
    score: float = Field(ge=0.0, le=1.0)
    recommendation: Literal["catalog_first", "research_candidate"]
    features: dict[str, float]
    reasons: list[str]
    mode: Literal["observer"] = "observer"
    calibration_status: Literal["uncalibrated_shadow"] = "uncalibrated_shadow"
    authoritative: Literal[False] = False


def assess_research_trigger_shadow(
    semantic_proposal: Mapping[str, Any] | None,
    *,
    catalog_coverage: float | None = None,
    retrieval_confidence: float | None = None,
    unknown_attribute_ratio: float | None = None,
    commercial_materiality: float = 0.0,
) -> ResearchTriggerObservation:
    """Return an inspectable heuristic observation, never an execution decision."""
    proposal = semantic_proposal if isinstance(semantic_proposal, Mapping) else {}
    concepts: Sequence[Any] = list(proposal.get("concepts") or [])[:4]
    unknowns = [
        item for item in list(proposal.get("material_unknowns") or [])[:8]
        if isinstance(item, Mapping)
    ]
    hypotheses = [
        item for item in list(proposal.get("workload_hypotheses") or [])[:5]
        if isinstance(item, Mapping)
        and str(item.get("evidence_coverage") or "unresolved") != "covered"
    ]
    material_concepts = sum(
        1 for item in concepts
        if isinstance(item, Mapping) and bool(item.get("material", True))
    )
    unresolved_ratio = min(1.0, len(unknowns) / max(1, material_concepts * 2))
    hypothesis_ambiguity = min(1.0, max(0, len(hypotheses) - 1) / 3)
    coverage_gap = 0.0 if catalog_coverage is None else 1.0 - _unit(catalog_coverage)
    retrieval_gap = 0.0 if retrieval_confidence is None else 1.0 - _unit(retrieval_confidence)
    attribute_gap = _unit(unknown_attribute_ratio or 0.0)
    materiality = _unit(commercial_materiality)
    semantic_gap = 1.0 if material_concepts else 0.0

    score = min(1.0, (
        0.30 * semantic_gap
        + 0.25 * unresolved_ratio
        + 0.15 * hypothesis_ambiguity
        + 0.10 * coverage_gap
        + 0.10 * retrieval_gap
        + 0.05 * attribute_gap
        + 0.05 * materiality
    ))
    if len(hypotheses) > 1 and any(
        str(item.get("resolution_source") or "").lower() in {"buyer", "either"}
        for item in unknowns
    ):
        state = "ambiguous_intent"
    elif material_concepts and unknowns:
        state = "unresolved_workload"
    else:
        state = "catalog_sufficient"
    reasons = [name for name, value in {
        "material_semantic_concept": semantic_gap,
        "material_unknowns": unresolved_ratio,
        "competing_hypotheses": hypothesis_ambiguity,
        "catalog_coverage_gap": coverage_gap,
        "retrieval_confidence_gap": retrieval_gap,
        "unknown_catalog_attributes": attribute_gap,
        "commercial_materiality": materiality,
    }.items() if value > 0]
    return ResearchTriggerObservation(
        state=state,
        score=round(score, 4),
        recommendation="research_candidate" if score >= 0.45 else "catalog_first",
        features={
            "semantic_gap": semantic_gap,
            "unresolved_ratio": round(unresolved_ratio, 4),
            "hypothesis_ambiguity": round(hypothesis_ambiguity, 4),
            "catalog_coverage_gap": round(coverage_gap, 4),
            "retrieval_confidence_gap": round(retrieval_gap, 4),
            "unknown_attribute_ratio": round(attribute_gap, 4),
            "commercial_materiality": round(materiality, 4),
        },
        reasons=reasons,
    )


def _unit(value: float) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0
