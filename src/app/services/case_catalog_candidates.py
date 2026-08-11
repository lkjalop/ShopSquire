"""Case-bound catalog candidate generation for ambiguity/research journeys.

The evidence reducer must never infer its candidate universe by reading every active
configuration.  This module turns an explicit storefront taxonomy context plus any
strong product-category phrase in the buyer's request into a bounded configuration
set.  Workload interpretation remains open vocabulary; only product sellability is
clamped to the pinned taxonomy and the current catalog context.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import select

from src.app.models.orm import ProductConfiguration
from src.app.services.taxonomy_registry import ancestors, get_node, search_nodes


_WORD = re.compile(r"[a-z0-9]+")


class CatalogCandidateSet(BaseModel):
    schema_version: Literal["catalog-candidate-set-v1"] = "catalog-candidate-set-v1"
    retained_purpose: str = Field(min_length=1, max_length=500)
    status: Literal["eligible", "out_of_category", "unresolved"]
    taxonomy_handle: str | None = None
    taxonomy_label: str | None = None
    taxonomy_source: Literal["explicit_query", "storefront_context", "unresolved"]
    configuration_ids: list[str] = Field(default_factory=list)
    excluded_configuration_ids: list[str] = Field(default_factory=list)
    reason: str


def _normal(value: str) -> str:
    return " ".join(_WORD.findall(str(value or "").lower()))


def _singular(value: str) -> str:
    words = _normal(value).split()
    if words and words[-1].endswith("s") and not words[-1].endswith("ss"):
        words[-1] = words[-1][:-1]
    return " ".join(words)


def _explicit_category(purpose: str, *, preferred_handle: str | None = None):
    """Return a taxonomy node only for a strong category-name phrase.

    This deliberately does not classify workload words such as ``render`` or ``CAD``
    as the product being purchased.  Semantic workload interpretation happens later;
    here we only detect buyer-named product categories such as ``standing desk`` or
    ``blood pressure monitor``.
    """

    words = _normal(purpose).split()
    matches: dict[str, tuple[int, int, object]] = {}
    for width in range(min(5, len(words)), 0, -1):
        for start in range(0, len(words) - width + 1):
            phrase = " ".join(words[start:start + width])
            if len(phrase) < 4:
                continue
            for node in search_nodes(phrase, limit=8):
                if _singular(node.name) != _singular(phrase):
                    continue
                matches[node.handle] = (width, node.depth, node)
    if not matches:
        return None
    ranked = list(matches.values())
    # When the buyer explicitly names the storefront product ("a laptop for drone
    # photogrammetry"), that purchase object outranks nouns describing the workload.
    # This is a taxonomy relationship rule, not a workload-word exception.
    related = [
        row for row in ranked
        if preferred_handle and _related(row[2].handle, preferred_handle)
    ]
    if related:
        ranked = related
    return max(ranked, key=lambda row: (row[0], row[1], row[2].handle))[2]


def _related(left_handle: str, right_handle: str) -> bool:
    if left_handle == right_handle:
        return True
    left_ancestors = {row.handle for row in ancestors(left_handle)}
    right_ancestors = {row.handle for row in ancestors(right_handle)}
    return left_handle in right_ancestors or right_handle in left_ancestors


def _derived_configuration_handle(row: ProductConfiguration) -> str | None:
    form = _normal(row.form_factor).replace(" ", "_")
    mobility = _normal(row.mobility).replace(" ", "_")
    device = _normal(row.device_class).replace(" ", "_")
    if form in {"laptop", "notebook"} or mobility.startswith("mobile") or device == "mobile_workstation":
        return "el-6-6"
    if form in {"desktop", "desktop_tower", "sff_desktop"} or device in {
        "desktop_workstation", "fixed_workstation",
    }:
        return "el-6-3"
    if form == "server" or device == "server":
        return "el-6-4"
    return None


def build_case_catalog_candidate_set(
    db,
    *,
    retained_purpose: str,
    tenant_id: str,
    storefront_taxonomy_handle: str | None,
) -> CatalogCandidateSet:
    purpose = " ".join(str(retained_purpose or "").split())[:500] or "Unresolved buyer request"
    context_node = get_node(str(storefront_taxonomy_handle or "").strip())
    explicit_node = _explicit_category(
        purpose,
        preferred_handle=context_node.handle if context_node is not None else None,
    )

    if explicit_node is not None and context_node is not None and not _related(
        explicit_node.handle, context_node.handle,
    ):
        return CatalogCandidateSet(
            retained_purpose=purpose,
            status="out_of_category",
            taxonomy_handle=explicit_node.handle,
            taxonomy_label=explicit_node.full_path,
            taxonomy_source="explicit_query",
            reason="buyer_named_category_outside_storefront_context",
        )

    selected = explicit_node or context_node
    source = "explicit_query" if explicit_node is not None else (
        "storefront_context" if context_node is not None else "unresolved"
    )
    if selected is None:
        return CatalogCandidateSet(
            retained_purpose=purpose,
            status="unresolved",
            taxonomy_source="unresolved",
            reason="no_product_category_or_storefront_context",
        )

    rows = db.execute(select(ProductConfiguration).where(
        ProductConfiguration.tenant_id == tenant_id,
        ProductConfiguration.active.is_(True),
    )).scalars().all()
    included: list[str] = []
    excluded: list[str] = []
    for row in rows:
        handle = _derived_configuration_handle(row)
        if handle is not None and _related(handle, selected.handle):
            included.append(row.id)
        else:
            excluded.append(row.id)
    return CatalogCandidateSet(
        retained_purpose=purpose,
        status="eligible" if included else "out_of_category",
        taxonomy_handle=selected.handle,
        taxonomy_label=selected.full_path,
        taxonomy_source=source,
        configuration_ids=sorted(included),
        excluded_configuration_ids=sorted(excluded),
        reason="query_specific_catalog_candidates" if included else "no_sellable_configuration_in_category",
    )


__all__ = ["CatalogCandidateSet", "build_case_catalog_candidate_set"]
