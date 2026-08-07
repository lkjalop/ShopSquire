"""Evaluation primitives for governed semantic research.

These metrics deliberately separate interpretation, routing, clarification, claim
grounding and report review. They do not combine unlike measurements into one pass rate.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class SealedResearchReportReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=1, max_length=120)
    reviewer_id: str = Field(min_length=2, max_length=120)
    reviewer_type: Literal["independent_human"] = "independent_human"
    accuracy: int = Field(ge=1, le=5)
    coverage: int = Field(ge=1, le=5)
    informativeness: int = Field(ge=1, le=5)
    clarity: int = Field(ge=1, le=5)
    consistency: int = Field(ge=1, le=5)
    novelty: int = Field(ge=1, le=5)
    sealed_at: str = Field(min_length=10, max_length=80)


def hypothesis_metrics(
    truth: Sequence[str], predictions: Mapping[str, float],
) -> dict[str, float]:
    labels = set(truth)
    proposed = {key for key, value in predictions.items() if float(value) > 0.0}
    recall = len(labels & proposed) / max(1, len(labels))
    universe = labels | set(predictions)
    brier = sum(
        (max(0.0, min(1.0, float(predictions.get(key, 0.0)))) - (1.0 if key in labels else 0.0)) ** 2
        for key in universe
    ) / max(1, len(universe))
    return {"recall": round(recall, 4), "brier": round(brier, 4)}


def binary_trigger_metrics(rows: Sequence[Mapping[str, Any]]) -> dict[str, float]:
    tp = fp = fn = 0
    for row in rows:
        expected = bool(row.get("expected_research"))
        observed = bool(row.get("observed_research"))
        tp += int(expected and observed)
        fp += int(not expected and observed)
        fn += int(expected and not observed)
    return {
        "precision": round(tp / max(1, tp + fp), 4),
        "recall": round(tp / max(1, tp + fn), 4),
    }


def clarification_metrics(rows: Sequence[Mapping[str, Any]]) -> dict[str, float]:
    asked = [row for row in rows if bool(row.get("asked"))]
    ineffective = sum(1 for row in asked if not bool(row.get("reduced_material_uncertainty")))
    regret = sum(
        max(0.0, float(row.get("best_available_utility") or 0.0)
            - float(row.get("selected_utility") or 0.0))
        for row in asked
    )
    return {
        "ineffective_question_rate": round(ineffective / max(1, len(asked)), 4),
        "mean_regret": round(regret / max(1, len(asked)), 4),
    }


def grounding_metrics(claims: Sequence[Mapping[str, Any]]) -> dict[str, float]:
    asserted = [item for item in claims if bool(item.get("presented"))]
    supported = [
        item for item in asserted
        if item.get("status") == "accepted" and item.get("source_id")
        and item.get("source_record_id") and item.get("observed_at")
    ]
    return {
        "unsupported_claim_rate": round(1.0 - len(supported) / max(1, len(asserted)), 4),
        "provenance_coverage": round(len(supported) / max(1, len(asserted)), 4),
    }


def relation_relevance(rows: Sequence[Mapping[str, Any]]) -> dict[str, float]:
    shown = [row for row in rows if bool(row.get("shown", True))]
    counts = {relation: 0 for relation in ("exact", "substitute", "complement", "irrelevant")}
    for row in shown:
        relation = str(row.get("relation") or "irrelevant")
        counts[relation if relation in counts else "irrelevant"] += 1
    useful = counts["exact"] + counts["substitute"] + counts["complement"]
    return {
        **{f"{key}_count": float(value) for key, value in counts.items()},
        "useful_precision": round(useful / max(1, len(shown)), 4),
        "exact_precision": round(counts["exact"] / max(1, len(shown)), 4),
    }
