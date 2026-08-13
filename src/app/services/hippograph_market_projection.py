"""Cohort-safe market projection from aggregate observations.

No buyer, case, session, email, or free-text event data can enter the output.
Small cohorts are suppressed rather than rounded into a potentially identifying
story. This projection is advisory market evidence and has no ranking authority.
"""
from __future__ import annotations

import hashlib
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class AggregateMarketObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str = Field(min_length=1, max_length=200)
    cohort_key: str = Field(min_length=1, max_length=200)
    metric: Literal[
        "search_demand", "zero_result_rate", "shortlist_rate", "conversion_rate",
        "return_rate", "stockout_rate", "units_sold", "revenue_cents",
    ]
    cohort_size: int = Field(ge=0)
    observation_count: int = Field(ge=0)
    value: float
    window_start: str
    window_end: str
    product_ref: str | None = Field(default=None, max_length=200)

    @field_validator("cohort_key")
    @classmethod
    def reject_individual_scope(cls, value: str) -> str:
        normalized = value.lower()
        if normalized.startswith(("user:", "uid:", "case:", "session:", "email:")):
            raise ValueError("individual_scope_forbidden")
        return value


class CohortMarketSignal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cohort_ref: str
    metric: str
    cohort_size_band: str
    observation_count: int
    value: float
    window_start: str
    window_end: str
    product_ref: str | None
    authority: Literal["aggregate_evidence_only"] = "aggregate_evidence_only"


class CohortMarketProjection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["hippograph-market-cohort-v1"] = "hippograph-market-cohort-v1"
    signals: list[CohortMarketSignal]
    suppressed_small_cohorts: int
    minimum_cohort_size: int
    contains_individual_identifiers: Literal[False] = False
    ranking_authority: Literal["none"] = "none"
    commerce_authority: Literal["none"] = "none"


def _band(size: int) -> str:
    if size < 10:
        return "5-9"
    if size < 25:
        return "10-24"
    if size < 100:
        return "25-99"
    return "100+"


def project_cohort_market_signals(
    observations: list[AggregateMarketObservation | dict],
    *,
    tenant_id: str,
    minimum_cohort_size: int = 5,
) -> CohortMarketProjection:
    minimum = max(5, int(minimum_cohort_size))
    signals: list[CohortMarketSignal] = []
    suppressed = 0
    for raw in observations:
        row = raw if isinstance(raw, AggregateMarketObservation) else AggregateMarketObservation.model_validate(raw)
        if row.tenant_id != tenant_id:
            continue
        if row.cohort_size < minimum:
            suppressed += 1
            continue
        cohort_ref = "cohort:" + hashlib.sha256(
            f"{tenant_id}|{row.cohort_key}".encode("utf-8")
        ).hexdigest()[:16]
        signals.append(CohortMarketSignal(
            cohort_ref=cohort_ref,
            metric=row.metric,
            cohort_size_band=_band(row.cohort_size),
            observation_count=row.observation_count,
            value=round(float(row.value), 4),
            window_start=row.window_start,
            window_end=row.window_end,
            product_ref=row.product_ref,
        ))
    signals.sort(key=lambda item: (item.metric, item.product_ref or "", item.cohort_ref))
    return CohortMarketProjection(
        signals=signals,
        suppressed_small_cohorts=suppressed,
        minimum_cohort_size=minimum,
    )


__all__ = [
    "AggregateMarketObservation", "CohortMarketProjection", "CohortMarketSignal",
    "project_cohort_market_signals",
]
