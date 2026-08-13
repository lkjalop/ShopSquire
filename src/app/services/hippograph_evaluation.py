"""Separate Hippograph recall quality from recommendation relevance quality."""
from __future__ import annotations

import math
from typing import Literal

from pydantic import BaseModel, ConfigDict


class RecallEvaluation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["hippograph-recall-eval-v1"] = "hippograph-recall-eval-v1"
    k: int
    precision_at_k: float
    recall_at_k: float
    reciprocal_rank: float
    relevant_recalled: list[str]
    purpose: Literal["graph_relatedness"] = "graph_relatedness"


class RecommendationEvaluation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["recommendation-relevance-eval-v1"] = "recommendation-relevance-eval-v1"
    k: int
    ndcg_at_k: float
    precision_at_k: float
    directly_relevant_count: int
    purpose: Literal["product_suitability"] = "product_suitability"


def evaluate_recall(
    recalled_entity_ids: list[str], relevant_entity_ids: set[str], *, k: int = 10,
) -> RecallEvaluation:
    size = max(1, int(k))
    recalled = list(dict.fromkeys(recalled_entity_ids))[:size]
    hits = [entity_id for entity_id in recalled if entity_id in relevant_entity_ids]
    first = next((index + 1 for index, entity_id in enumerate(recalled) if entity_id in relevant_entity_ids), None)
    return RecallEvaluation(
        k=size,
        precision_at_k=round(len(hits) / size, 6),
        recall_at_k=round(len(hits) / max(1, len(relevant_entity_ids)), 6),
        reciprocal_rank=round(1.0 / first, 6) if first else 0.0,
        relevant_recalled=hits,
    )


def evaluate_recommendations(
    ranked_product_ids: list[str], relevance_by_product: dict[str, int], *, k: int = 10,
) -> RecommendationEvaluation:
    size = max(1, int(k))
    ranked = list(dict.fromkeys(ranked_product_ids))[:size]
    grades = [max(0, min(2, int(relevance_by_product.get(product_id, 0)))) for product_id in ranked]
    dcg = sum((2 ** grade - 1) / math.log2(index + 2) for index, grade in enumerate(grades))
    ideal = sorted((max(0, min(2, int(value))) for value in relevance_by_product.values()), reverse=True)[:size]
    idcg = sum((2 ** grade - 1) / math.log2(index + 2) for index, grade in enumerate(ideal))
    return RecommendationEvaluation(
        k=size,
        ndcg_at_k=round(dcg / idcg, 6) if idcg else 0.0,
        precision_at_k=round(sum(grade == 2 for grade in grades) / size, 6),
        directly_relevant_count=sum(grade == 2 for grade in grades),
    )


__all__ = [
    "RecallEvaluation", "RecommendationEvaluation", "evaluate_recall",
    "evaluate_recommendations",
]
