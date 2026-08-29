"""Typed, deterministic buyer copy built only from accepted decision evidence."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class BuyerResearchReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str
    publisher_labels: list[str]
    requirements_established: int = Field(ge=0)
    context_claims: int = Field(ge=0)
    unresolved_count: int = Field(ge=0)
    product_identity_status: Literal["separately_verified"] = "separately_verified"
    availability_status: Literal["separately_verified"] = "separately_verified"


class ProductNarrationSentence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sku: str
    sentence: str
    evidence_basis: Literal["verified", "conditional", "failed"]


class TypedNarrationProjection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    purpose: str
    accepted_requirements: list[dict[str, Any]]
    shelf_summary: str
    top_product_sentences: list[ProductNarrationSentence] = Field(max_length=3)
    reranking_summary: str


def project_research_explainability(
    *, purpose: str, research: dict[str, Any], shelves: dict[str, Any],
    delta: list[dict[str, Any]],
) -> tuple[BuyerResearchReceipt, TypedNarrationProjection]:
    claims = list(research.get("claims") or [])
    context = list(research.get("context_claims") or [])
    unresolved = list(research.get("unresolved") or [])
    publishers = list(dict.fromkeys(
        str(row.get("publisher") or row.get("source_id") or "official publisher")
        for row in research.get("source_execution") or []
    ))
    if len(publishers) == 1:
        subject = (
            f"{publishers[0]}'s official context"
            if context and not claims
            else f"{publishers[0]}'s official requirements"
        )
    else:
        subject = f"{len(publishers)} official publisher sources"
    if claims:
        summary = (
            f"Researched {subject}. {len(claims)} requirement"
            f"{'s were' if len(claims) != 1 else ' was'} established; product identity "
            "and availability remain separately verified."
        )
    elif context:
        summary = (
            f"Researched {subject}, but it established context rather than product "
            "requirements. The shortlist remains provisional."
        )
    else:
        summary = (
            f"Research checked {subject}, but no accepted requirements were established. "
            "The shortlist remains provisional."
        )
    receipt = BuyerResearchReceipt(
        summary=summary, publisher_labels=publishers,
        requirements_established=len(claims), context_claims=len(context),
        unresolved_count=len(unresolved),
    )

    narration = project_product_shelf_narration(
        purpose=purpose,
        shelves=shelves,
        accepted_requirements=claims,
        delta=delta,
    )
    return receipt, narration


def project_product_shelf_narration(
    *, purpose: str, shelves: dict[str, Any],
    accepted_requirements: list[dict[str, Any]] | None = None,
    delta: list[dict[str, Any]] | None = None,
) -> TypedNarrationProjection:
    """Explain a shelf from its reduced product evidence, even before research.

    This projection never invents requirements or changes rank.  It gives the
    buyer an immediate product-specific reason while live/model narration is
    still optional and authority-free.
    """

    shelf_rows = list(shelves.get("shelves") or [])
    leading = list(shelf_rows[0].get("initial") or []) if shelf_rows else []
    qualified = sum(str(row.get("fit_status")) == "qualified" for row in leading)
    shelf_summary = (
        f"The leading shelf has {len(leading)} options for the retained purpose; "
        f"{qualified} have verified exact-configuration fit and the remainder stay conditional."
    )
    sentences = [_product_sentence(row) for row in leading[:3]]
    moved = [
        row for row in list(delta or [])
        if int(row.get("movement") or 0) != 0
    ]
    if moved:
        first = moved[0]
        reranking_summary = (
            f"Research changed {len(moved)} ranked position"
            f"{'s' if len(moved) != 1 else ''}; {first.get('sku')} moved because "
            f"{first.get('reason') or 'verified evidence changed its fit status'}."
        )
    else:
        reranking_summary = (
            "Research did not change the leading order; it updated evidence status and "
            "kept unresolved gaps visible."
        )
    accepted = [{
        key: claim.get(key) for key in (
            "claim_id", "attribute", "attribute_key", "operator", "value", "unit",
            "requirement_class", "condition", "source_id", "freshness_status",
        ) if claim.get(key) is not None
    } for claim in list(accepted_requirements or [])]
    return TypedNarrationProjection(
        purpose=purpose,
        accepted_requirements=accepted,
        shelf_summary=shelf_summary,
        top_product_sentences=sentences,
        reranking_summary=reranking_summary,
    )


def _product_sentence(row: dict[str, Any]) -> ProductNarrationSentence:
    title = str(row.get("title") or row.get("product", {}).get("sku") or "This option")
    sku = str(row.get("product", {}).get("sku") or row.get("identity_key") or "unknown")
    misses = list(row.get("misses") or [])
    unknowns = list(row.get("unknowns") or [])
    compromises = list(row.get("compromises") or [])
    fit = str(row.get("fit_status") or "conditional")
    if misses:
        sentence = f"{title} is not qualified because it misses {', '.join(misses[:2])}."
        basis: Literal["verified", "conditional", "failed"] = "failed"
    elif fit == "qualified":
        availability = str((row.get("explanation") or {}).get("availability_note") or "").strip()
        sentence = f"{title} has verified fit for the accepted requirements"
        sentence += f"; {availability.rstrip('.')}" if availability else " with no verified minimum miss"
        sentence += "."
        basis = "verified"
    elif not any((row.get("meets"), unknowns, compromises, misses)):
        form_factor = str(
            (row.get("product") or {}).get("form_factor") or "product"
        ).replace("_", " ")
        budget_outcome = str(
            (row.get("commercial_decision") or {}).get("budget_outcome") or ""
        )
        budget_phrase = (
            " within the stated budget" if budget_outcome == "within"
            else " outside the stated budget" if budget_outcome == "over"
            else ""
        )
        sentence = (
            f"{title} is shown as a {form_factor} catalog candidate{budget_phrase}; "
            "it is not yet a verified recommendation because no accepted capability "
            "requirements distinguish it."
        )
        basis = "conditional"
    else:
        gap = (unknowns or compromises or ["exact capability evidence remains incomplete"])[0]
        sentence = f"{title} remains conditional because {gap}."
        basis = "conditional"
    return ProductNarrationSentence(sku=sku, sentence=sentence, evidence_basis=basis)
