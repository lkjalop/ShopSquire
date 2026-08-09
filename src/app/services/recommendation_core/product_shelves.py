"""Deterministic product-shelf projection for ambiguous workload exploration.

The reducer is deliberately independent of retrieval, UI, and narration.  It
partitions already-ranked catalog candidates into a shared shelf and optional
hypothesis shelves, while preserving three boundaries:

* a verified hard failure is never presented as qualified;
* missing or unresolved evidence is conditional, not a pass;
* evidence belongs to one exact product configuration and cannot be borrowed
  by another variant with the same marketing SKU or title.
"""
from __future__ import annotations

import hashlib
from typing import Literal, Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.app.services.recommendation_core.workload_decision import (
    ProductConfigurationIdentity,
    WorkloadDecision,
)


FitStatus = Literal["qualified", "conditional", "failed"]
BudgetBand = Literal["best", "within_budget", "stretch"]
FreshnessStatus = Literal["fresh", "stale", "unknown"]


class EvidenceFreshnessProjection(BaseModel):
    """Independent clocks; a fresh specification never refreshes price or stock."""

    model_config = ConfigDict(extra="forbid")

    specification: FreshnessStatus = "unknown"
    specification_observed_at: str | None = None
    price: FreshnessStatus = "unknown"
    price_observed_at: str | None = None
    availability: FreshnessStatus = "unknown"
    availability_observed_at: str | None = None


class AvailabilityProjection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    location_id: str
    status: str
    quantity: int | None = None
    lead_time_min_days: int | None = None
    lead_time_max_days: int | None = None
    observed_at: str | None = None
    freshness_status: FreshnessStatus = "unknown"


def configuration_identity_key(product: ProductConfigurationIdentity) -> str:
    """Return a stable key for the exact decision-material configuration."""
    material = "|".join(
        (
            product.sku.strip(),
            product.identifier_type.strip(),
            product.identifier.strip(),
            product.configuration_hash or "unresolved",
            product.form_factor,
        )
    )
    return "pc-" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]


def _same_configuration(
    left: ProductConfigurationIdentity, right: ProductConfigurationIdentity
) -> bool:
    return configuration_identity_key(left) == configuration_identity_key(right)


class ShelfCandidateInput(BaseModel):
    """One catalog configuration and its independently reduced scope decisions.

    ``fit_by_scope`` uses ``shared`` for the intersection floor and hypothesis
    identifiers for divergent scopes.  ``None`` explicitly means the candidate
    is eligible for provisional exploration but no decision ledger exists yet.
    """

    model_config = ConfigDict(extra="forbid")

    product: ProductConfigurationIdentity
    title: str = Field(min_length=1, max_length=500)
    price_cents: int = Field(ge=0)
    currency: str = Field(default="AUD", min_length=3, max_length=3)
    relevance_score: float = Field(default=0.0, ge=0.0)
    evidence_freshness: EvidenceFreshnessProjection = Field(
        default_factory=EvidenceFreshnessProjection,
    )
    availability: list[AvailabilityProjection] = Field(default_factory=list, max_length=64)
    fit_by_scope: dict[str, WorkloadDecision | None] = Field(
        default_factory=dict, max_length=8
    )

    @model_validator(mode="after")
    def decisions_belong_to_this_configuration(self) -> "ShelfCandidateInput":
        for scope_id, decision in self.fit_by_scope.items():
            if not scope_id.strip():
                raise ValueError("blank_scope_id")
            if decision is not None and not _same_configuration(
                self.product, decision.product
            ):
                raise ValueError(
                    f"decision_configuration_mismatch:{scope_id}:"
                    f"{decision.product.sku}"
                )
        return self


class ProductCardExplanation(BaseModel):
    """Buyer-visible deterministic copy backed only by the reduced fit ledger."""

    model_config = ConfigDict(extra="forbid")

    summary: str = Field(max_length=700)
    evidence_basis: Literal["verified_exact", "conditional", "provisional"]
    budget_note: str | None = Field(default=None, max_length=240)
    availability_note: str | None = Field(default=None, max_length=240)
    claim_refs: list[str] = Field(default_factory=list, max_length=128)


class ShelfProduct(BaseModel):
    model_config = ConfigDict(extra="forbid")

    identity_key: str
    product: ProductConfigurationIdentity
    title: str
    price_cents: int
    currency: str
    fit_status: FitStatus
    decision_id: str | None = None
    relevance_score: float
    meets: list[str] = Field(default_factory=list, max_length=12)
    conditional: list[str] = Field(default_factory=list, max_length=12)
    unknowns: list[str] = Field(default_factory=list, max_length=12)
    misses: list[str] = Field(default_factory=list, max_length=12)
    compromises: list[str] = Field(default_factory=list, max_length=12)
    why_ranked: str = Field(default="Provisional catalog exploration", max_length=500)
    explanation: ProductCardExplanation | None = None
    requirement_claim_ids: list[str] = Field(default_factory=list, max_length=64)
    capability_claim_ids: list[str] = Field(default_factory=list, max_length=64)
    freshness_status: Literal["fresh", "stale", "unknown", "mixed"] = "unknown"
    evidence_freshness: EvidenceFreshnessProjection = Field(
        default_factory=EvidenceFreshnessProjection,
    )
    availability: list[AvailabilityProjection] = Field(default_factory=list, max_length=64)


class ProductShelf(BaseModel):
    model_config = ConfigDict(extra="forbid")

    shelf_id: str
    scope_id: str
    scope_label: str
    budget_band: BudgetBand
    budget_cents: int | None = None
    initial: list[ShelfProduct] = Field(default_factory=list, max_length=3)
    next_page: list[ShelfProduct] = Field(default_factory=list, max_length=5)
    remaining_count: int = Field(default=0, ge=0)


class ShelfExclusion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope_id: str
    identity_key: str
    sku: str
    reason: Literal["verified_hard_failure"]
    decision_id: str | None = None


class ProductShelfProjection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["product-shelves-v1"] = "product-shelves-v1"
    shelves: list[ProductShelf] = Field(default_factory=list)
    exclusions: list[ShelfExclusion] = Field(default_factory=list)


def _fit_status(decision: WorkloadDecision | None) -> FitStatus:
    if decision is None:
        return "conditional"
    # A product may only be excluded on an accepted, verified hard failure.
    # An unverified below-minimum observation remains conditional even if an
    # upstream legacy reducer labelled the aggregate result not-qualified.
    if any(
        row.verdict == "below_minimum" and row.verification_status == "verified"
        for row in decision.fit_ledger
    ):
        return "failed"
    if (
        decision.overall_decision
        in {"qualified_for_stated_scope", "over_spec_for_stated_scope"}
        and decision.critic.status == "pass"
        and decision.product.exact
    ):
        return "qualified"
    return "conditional"


def _ordered(products: Sequence[ShelfProduct]) -> list[ShelfProduct]:
    return sorted(
        products,
        key=lambda item: (
            0 if item.fit_status == "qualified" else 1,
            -item.relevance_score,
            item.price_cents,
            item.identity_key,
        ),
    )


def _card_explanation(
    decision: WorkloadDecision | None, status: FitStatus,
) -> ProductCardExplanation:
    if decision is None:
        return ProductCardExplanation(
            summary="This configuration is shown for provisional catalog exploration; no fit ledger has been compiled.",
            evidence_basis="provisional",
        )
    meets = [
        row.attribute_label for row in decision.fit_ledger
        if row.verdict in {"meets_minimum", "meets_recommended"}
    ]
    gaps = [
        row.attribute_label for row in decision.fit_ledger
        if row.verdict in {"unknown", "contested"}
    ]
    misses = [
        row.attribute_label for row in decision.fit_ledger
        if row.verdict == "below_minimum" and row.requirement_class == "minimum"
    ]
    compromises = [
        row.attribute_label for row in decision.fit_ledger
        if row.verdict == "below_minimum" and row.requirement_class != "minimum"
    ]
    if status == "qualified":
        summary = (
            f"Exact-configuration evidence meets {len(meets)} accepted requirement"
            f"{'s' if len(meets) != 1 else ''}."
        )
        evidence_basis: Literal["verified_exact", "conditional", "provisional"] = "verified_exact"
    else:
        reasons: list[str] = []
        if gaps:
            reasons.append("not verified: " + ", ".join(dict.fromkeys(gaps)))
        if misses:
            reasons.append("minimum misses: " + ", ".join(dict.fromkeys(misses)))
        if compromises:
            reasons.append("recommended compromises: " + ", ".join(dict.fromkeys(compromises)))
        summary = "Conditional fit because " + "; ".join(reasons) + "." if reasons else (
            "Conditional fit because the accepted scope or exact-configuration evidence is incomplete."
        )
        evidence_basis = "conditional"
    budget_note = (
        "Outside the buyer's stated budget ceiling."
        if decision.budget_status == "over" else
        "Within the buyer's stated budget ceiling."
        if decision.budget_status == "within" else None
    )
    availability_note = (
        "Fresh availability evidence reports this configuration available."
        if decision.availability_status == "available" else
        "Fresh availability evidence reports this configuration unavailable."
        if decision.availability_status == "unavailable" else
        "Current availability is not verified."
    )
    claim_refs = list(dict.fromkeys(
        claim_id for row in decision.fit_ledger
        for claim_id in [*row.requirement_claim_ids, *row.capability_claim_ids]
    ))
    return ProductCardExplanation(
        summary=summary, evidence_basis=evidence_basis,
        budget_note=budget_note, availability_note=availability_note,
        claim_refs=claim_refs,
    )


def _page(
    *,
    shelf_id: str,
    scope_id: str,
    scope_label: str,
    budget_band: BudgetBand,
    budget_cents: int | None,
    products: Sequence[ShelfProduct],
) -> ProductShelf:
    ordered = _ordered(products)
    return ProductShelf(
        shelf_id=shelf_id,
        scope_id=scope_id,
        scope_label=scope_label,
        budget_band=budget_band,
        budget_cents=budget_cents,
        initial=ordered[:3],
        next_page=ordered[3:8],
        remaining_count=max(0, len(ordered) - 8),
    )


def build_product_shelves(
    candidates: Sequence[ShelfCandidateInput],
    *,
    hypothesis_ids: Sequence[str] = (),
    scope_labels: Mapping[str, str] | None = None,
    budget_cents: int | None = None,
) -> ProductShelfProjection:
    """Build shared and hypothesis shelves with deterministic 3+5 paging.

    A budget creates separate within-budget and stretch shelves.  With no
    budget, ranking is price-agnostic except for the deterministic tie-breaker;
    relevance and qualification decide the result before price.
    """
    if budget_cents is not None and budget_cents < 0:
        raise ValueError("budget_cents_must_be_non_negative")
    labels = dict(scope_labels or {})
    scope_ids = ["shared"]
    for hypothesis_id in hypothesis_ids:
        normalized = str(hypothesis_id).strip()
        if normalized and normalized != "shared" and normalized not in scope_ids:
            scope_ids.append(normalized)

    seen: set[str] = set()
    bounded_candidates = list(candidates)
    for candidate in bounded_candidates:
        identity_key = configuration_identity_key(candidate.product)
        if identity_key in seen:
            raise ValueError(f"duplicate_candidate_configuration:{identity_key}")
        seen.add(identity_key)

    shelves: list[ProductShelf] = []
    exclusions: list[ShelfExclusion] = []
    for scope_id in scope_ids:
        eligible: list[ShelfProduct] = []
        for candidate in bounded_candidates:
            if scope_id not in candidate.fit_by_scope:
                continue
            decision = candidate.fit_by_scope[scope_id]
            status = _fit_status(decision)
            identity_key = configuration_identity_key(candidate.product)
            if status == "failed":
                exclusions.append(
                    ShelfExclusion(
                        scope_id=scope_id,
                        identity_key=identity_key,
                        sku=candidate.product.sku,
                        reason="verified_hard_failure",
                        decision_id=decision.decision_id if decision else None,
                    )
                )
                continue
            explanation = _card_explanation(decision, status)
            eligible.append(
                ShelfProduct(
                    identity_key=identity_key,
                    product=candidate.product,
                    title=candidate.title,
                    price_cents=candidate.price_cents,
                    currency=candidate.currency.upper(),
                    fit_status=status,
                    decision_id=decision.decision_id if decision else None,
                    relevance_score=candidate.relevance_score,
                    meets=(
                        [row.attribute_label for row in decision.fit_ledger
                         if row.verdict in {"meets_minimum", "meets_recommended"}]
                        if decision else []
                    ),
                    conditional=(
                        [row.scope_caveat for row in decision.fit_ledger if row.scope_caveat]
                        if decision else []
                    ),
                    unknowns=(
                        [row.attribute_label for row in decision.fit_ledger
                         if row.verdict in {"unknown", "contested"}]
                        if decision else ["fit ledger not recorded"]
                    ),
                    misses=(
                        [row.attribute_label for row in decision.fit_ledger
                         if row.verdict == "below_minimum"
                         and row.requirement_class == "minimum"]
                        if decision else []
                    ),
                    compromises=(
                        [row.attribute_label for row in decision.fit_ledger
                         if row.verdict == "below_minimum"
                         and row.requirement_class != "minimum"]
                        if decision else []
                    ),
                    why_ranked=explanation.summary,
                    explanation=explanation,
                    requirement_claim_ids=(
                        list(dict.fromkeys(
                            claim_id for row in decision.fit_ledger
                            for claim_id in row.requirement_claim_ids
                        )) if decision else []
                    ),
                    capability_claim_ids=(
                        list(dict.fromkeys(
                            claim_id for row in decision.fit_ledger
                            for claim_id in row.capability_claim_ids
                        )) if decision else []
                    ),
                    freshness_status=(
                        "mixed" if decision and len({row.freshness_status for row in decision.fit_ledger}) > 1
                        else decision.fit_ledger[0].freshness_status
                        if decision and decision.fit_ledger else "unknown"
                    ),
                    evidence_freshness=candidate.evidence_freshness,
                    availability=candidate.availability,
                )
            )

        scope_label = labels.get(
            scope_id, "Best across shared needs" if scope_id == "shared" else scope_id
        )
        if budget_cents is None:
            if eligible:
                shelves.append(
                    _page(
                        shelf_id=scope_id,
                        scope_id=scope_id,
                        scope_label=scope_label,
                        budget_band="best",
                        budget_cents=None,
                        products=eligible,
                    )
                )
            continue

        within = [item for item in eligible if item.price_cents <= budget_cents]
        stretch = [item for item in eligible if item.price_cents > budget_cents]
        if within:
            shelves.append(
                _page(
                    shelf_id=f"{scope_id}:within_budget",
                    scope_id=scope_id,
                    scope_label=scope_label,
                    budget_band="within_budget",
                    budget_cents=budget_cents,
                    products=within,
                )
            )
        if stretch:
            shelves.append(
                _page(
                    shelf_id=f"{scope_id}:stretch",
                    scope_id=scope_id,
                    scope_label=scope_label,
                    budget_band="stretch",
                    budget_cents=budget_cents,
                    products=stretch,
                )
            )

    return ProductShelfProjection(shelves=shelves, exclusions=exclusions)
