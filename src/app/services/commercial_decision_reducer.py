"""Deterministic product/offer decision reducer.

The reducer owns commercial classification only. It performs no retrieval,
supplier contact, narration, or cart mutation and never promotes missing
evidence into compatibility.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


DecisionStatus = Literal[
    "QUALIFIED_NOW", "QUALIFIED_PARTIAL", "QUALIFIED_LATE",
    "CONDITIONAL_NOW", "CONDITIONAL_LATE", "FAILED_REQUIREMENT",
    "OVER_BUDGET", "UNVERIFIED",
]
FitTier = Literal["qualified", "conditional", "failed", "unverified"]
QuantityOutcome = Literal["complete_by_deadline", "partial", "late", "unknown"]
BudgetOutcome = Literal["within", "over", "not_stated"]


class CommercialCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sku: str = Field(min_length=1, max_length=120)
    exact_identity: bool
    actual_form_factor: str | None = Field(default=None, max_length=80)
    mandatory_form_factor: str | None = Field(default=None, max_length=80)
    verified_minimum_misses: list[str] = Field(default_factory=list, max_length=32)
    recommendation_compromises: list[str] = Field(default_factory=list, max_length=32)
    material_unknowns: list[str] = Field(default_factory=list, max_length=32)
    specification_freshness: Literal["fresh", "stale", "unknown"] = "unknown"
    unit_price_cents: int | None = Field(default=None, ge=0, le=1_000_000_000)
    currency: str = Field(default="AUD", min_length=3, max_length=3)
    budget_per_unit_cents: int | None = Field(default=None, ge=0, le=1_000_000_000)
    budget_total_cents: int | None = Field(default=None, ge=0, le=1_000_000_000_000)
    requested_quantity: int = Field(ge=1, le=1_000_000)
    local_available_now: int | None = Field(default=None, ge=0, le=1_000_000)
    supplier_quantity: int | None = Field(default=None, ge=0, le=1_000_000)
    supplier_lead_time_days: int | None = Field(default=None, ge=0, le=3650)
    deadline_days: int | None = Field(default=None, ge=0, le=3650)
    relationship: Literal["exact", "compatible_substitute"] = "exact"

    @model_validator(mode="after")
    def validate_budget_currency(self) -> "CommercialCandidate":
        self.currency = self.currency.upper()
        return self


class CommercialDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["commercial-decision-v1"] = "commercial-decision-v1"
    sku: str
    status: DecisionStatus
    fit_tier: FitTier
    quantity_outcome: QuantityOutcome
    budget_outcome: BudgetOutcome
    available_by_deadline: int | None
    shortfall: int | None
    reasons: list[str]
    cart_authority: Literal["none"] = "none"
    supplier_send_authority: Literal["none"] = "none"
    resolution_owner: Literal["catalog", "buyer", "supplier", "tenant_policy"]


def reduce_commercial_candidate(candidate: CommercialCandidate) -> CommercialDecision:
    reasons: list[str] = []
    local = candidate.local_available_now
    supplier = candidate.supplier_quantity
    supplier_by_deadline = (
        supplier is not None
        and candidate.supplier_lead_time_days is not None
        and (
            candidate.deadline_days is None
            or candidate.supplier_lead_time_days <= candidate.deadline_days
        )
    )
    available_by_deadline = None
    if local is not None or supplier is not None:
        available_by_deadline = int(local or 0) + int(supplier or 0) if supplier_by_deadline else int(local or 0)
    shortfall = (
        max(0, candidate.requested_quantity - available_by_deadline)
        if available_by_deadline is not None else None
    )

    if available_by_deadline is None:
        quantity_outcome: QuantityOutcome = "unknown"
    elif shortfall and supplier and candidate.supplier_lead_time_days is not None \
            and candidate.deadline_days is not None \
            and candidate.supplier_lead_time_days > candidate.deadline_days \
            and int(local or 0) + supplier >= candidate.requested_quantity:
        quantity_outcome = "late"
        reasons.append("Full quantity is available only after the requested deadline.")
    elif shortfall:
        quantity_outcome = "partial"
        reasons.append(f"Verified supply is short by {shortfall} unit(s) within the requested window.")
    else:
        quantity_outcome = "complete_by_deadline"

    total_cents = (
        candidate.unit_price_cents * candidate.requested_quantity
        if candidate.unit_price_cents is not None else None
    )
    over_unit = (
        candidate.budget_per_unit_cents is not None
        and candidate.unit_price_cents is not None
        and candidate.unit_price_cents > candidate.budget_per_unit_cents
    )
    over_total = (
        candidate.budget_total_cents is not None
        and total_cents is not None
        and total_cents > candidate.budget_total_cents
    )
    if candidate.budget_per_unit_cents is None and candidate.budget_total_cents is None:
        budget_outcome: BudgetOutcome = "not_stated"
    else:
        budget_outcome = "over" if over_unit or over_total else "within"

    form_factor_failure = bool(
        candidate.mandatory_form_factor and candidate.actual_form_factor
        and candidate.mandatory_form_factor != candidate.actual_form_factor
    )
    if candidate.verified_minimum_misses or form_factor_failure:
        if candidate.verified_minimum_misses:
            reasons.append("Verified minimum misses: " + ", ".join(candidate.verified_minimum_misses) + ".")
        if form_factor_failure:
            reasons.append(
                f"Mandatory form factor is {candidate.mandatory_form_factor}; "
                f"this configuration is {candidate.actual_form_factor}."
            )
        return CommercialDecision(
            sku=candidate.sku, status="FAILED_REQUIREMENT", fit_tier="failed",
            quantity_outcome=quantity_outcome, budget_outcome=budget_outcome,
            available_by_deadline=available_by_deadline, shortfall=shortfall,
            reasons=reasons, resolution_owner="catalog",
        )

    if budget_outcome == "over":
        reasons.append("The requested quantity exceeds the stated unit or total budget.")
        return CommercialDecision(
            sku=candidate.sku, status="OVER_BUDGET", fit_tier="qualified",
            quantity_outcome=quantity_outcome, budget_outcome=budget_outcome,
            available_by_deadline=available_by_deadline, shortfall=shortfall,
            reasons=reasons, resolution_owner="buyer",
        )

    if not candidate.exact_identity or candidate.specification_freshness == "unknown":
        reasons.append("Exact-configuration capability evidence is not verified.")
        return CommercialDecision(
            sku=candidate.sku, status="UNVERIFIED", fit_tier="unverified",
            quantity_outcome=quantity_outcome, budget_outcome=budget_outcome,
            available_by_deadline=available_by_deadline, shortfall=shortfall,
            reasons=reasons, resolution_owner="catalog",
        )

    conditional = bool(
        candidate.relationship == "compatible_substitute"
        or candidate.material_unknowns
        or candidate.recommendation_compromises
        or candidate.specification_freshness == "stale"
    )
    if candidate.relationship == "compatible_substitute":
        reasons.append("This is a proposed substitute and requires explicit buyer acceptance.")
    if candidate.material_unknowns:
        reasons.append("Material unknowns: " + ", ".join(candidate.material_unknowns) + ".")
    if candidate.recommendation_compromises:
        reasons.append("Recommendation compromises: " + ", ".join(candidate.recommendation_compromises) + ".")
    if candidate.specification_freshness == "stale":
        reasons.append("Specification evidence is stale.")

    if conditional:
        status: DecisionStatus = (
            "CONDITIONAL_NOW" if quantity_outcome == "complete_by_deadline"
            else "CONDITIONAL_LATE"
        )
        fit_tier: FitTier = "conditional"
    else:
        status = (
            "QUALIFIED_NOW" if quantity_outcome == "complete_by_deadline"
            else "QUALIFIED_PARTIAL" if quantity_outcome == "partial"
            else "QUALIFIED_LATE"
        )
        fit_tier = "qualified"
    if not reasons:
        reasons.append("Verified requirements, budget, quantity and delivery window are satisfied.")
    return CommercialDecision(
        sku=candidate.sku, status=status, fit_tier=fit_tier,
        quantity_outcome=quantity_outcome, budget_outcome=budget_outcome,
        available_by_deadline=available_by_deadline, shortfall=shortfall,
        reasons=reasons,
        resolution_owner="buyer" if conditional else "supplier" if quantity_outcome != "complete_by_deadline" else "catalog",
    )


__all__ = ["CommercialCandidate", "CommercialDecision", "DecisionStatus", "reduce_commercial_candidate"]
