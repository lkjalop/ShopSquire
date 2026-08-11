"""Authoritative, workload-agnostic adjudication after catalog retrieval."""
from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class PostCatalogAdjudication(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["post-catalog-adjudication-v1"] = "post-catalog-adjudication-v1"
    requirements_established: bool
    evidence_qualified_product_count: int = Field(ge=0)
    retrieval_count: int = Field(ge=0)
    material_attribute_coverage_gap: float = Field(ge=0.0, le=1.0)
    unresolved_explicit_constraints: list[str] = Field(default_factory=list, max_length=12)
    category_similarity_only: bool
    qualification_authority: Literal["positive_evidence", "none"]
    research_needed: bool
    reason_codes: list[str]


_EXPLICIT_EVIDENCE_CONSTRAINTS = {
    "vendor_certification": re.compile(
        r"\b(?:certif(?:ied|ication)|officially\s+supported|approved\s+hardware|support\s+matrix)\b",
        re.IGNORECASE,
    ),
    "security_status": re.compile(
        r"\b(?:security\s+advisor(?:y|ies)|firmware\s+(?:issue|advisory)|critical\s+"
        r"(?:vulnerability|firmware)|PSIRT|CVE|KEV)\b",
        re.IGNORECASE,
    ),
    "platform_support": re.compile(
        r"\b(?:Linux\s+certif(?:ied|ication)|dock\s+compatib|operating\s+system\s+support)\b",
        re.IGNORECASE,
    ),
}


def explicit_evidence_constraints(text: str) -> list[str]:
    """Extract vertical-agnostic constraints that require positive evidence."""

    value = str(text or "")
    return [
        constraint
        for constraint, pattern in _EXPLICIT_EVIDENCE_CONSTRAINTS.items()
        if pattern.search(value)
    ]


def adjudicate_post_catalog(
    *,
    normalized_requirement_count: int,
    evidence_qualified_product_count: int,
    retrieval_count: int,
    material_attribute_coverage_gap: float,
    unresolved_explicit_constraints: list[str] | tuple[str, ...] = (),
    category_similarity_only: bool = False,
) -> PostCatalogAdjudication:
    """Prevent retrieval success from being confused with evidenced suitability."""

    requirements_established = normalized_requirement_count > 0
    qualified = max(0, int(evidence_qualified_product_count)) if requirements_established else 0
    gap = max(0.0, min(1.0, float(material_attribute_coverage_gap)))
    unresolved = list(dict.fromkeys(
        str(item).strip() for item in unresolved_explicit_constraints if str(item).strip()
    ))[:12]
    reasons: list[str] = []
    if not requirements_established:
        reasons.append("no_normalized_requirements")
    if qualified == 0:
        reasons.append("zero_evidence_qualified_products")
    if gap >= 0.50:
        reasons.append("high_material_attribute_coverage_gap")
    if unresolved:
        reasons.append("explicit_constraints_unresolved")
    if category_similarity_only:
        reasons.append("category_similarity_only")
    research_needed = bool(
        (not requirements_established and (retrieval_count > 0 or category_similarity_only))
        or qualified == 0
        or gap >= 0.50
        or unresolved
    )
    positive = bool(requirements_established and qualified > 0 and not unresolved)
    return PostCatalogAdjudication(
        requirements_established=requirements_established,
        evidence_qualified_product_count=qualified,
        retrieval_count=max(0, int(retrieval_count)),
        material_attribute_coverage_gap=gap,
        unresolved_explicit_constraints=unresolved,
        category_similarity_only=bool(category_similarity_only),
        qualification_authority="positive_evidence" if positive else "none",
        research_needed=research_needed,
        reason_codes=reasons,
    )


__all__ = [
    "PostCatalogAdjudication", "adjudicate_post_catalog", "explicit_evidence_constraints",
]
