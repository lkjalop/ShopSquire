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
from src.app.services.taxonomy_registry import (
    ancestors,
    get_node,
    primary_sold_node,
    search_nodes,
    sells_within,
    sold_nodes,
)


_WORD = re.compile(r"[a-z0-9]+")


class CatalogScope(BaseModel):
    """Server-authoritative catalog boundary for one case revision.

    A browser-provided taxonomy handle is context only.  The selected root is
    always checked against the tenant's sold taxonomy and may be replaced by an
    explicit buyer-authored product form factor or the tenant's grounded primary
    storefront category.
    """

    schema_version: Literal["catalog-scope-v1"] = "catalog-scope-v1"
    case_id: str | None = None
    case_revision: int | None = Field(default=None, ge=1)
    tenant_id: str = Field(min_length=1, max_length=120)
    requested_product_form_factor: str | None = None
    allowed_taxonomy_roots: list[str] = Field(default_factory=list)
    selected_taxonomy_root: str | None = None
    source: Literal[
        "buyer_explicit", "tenant_primary", "validated_client_context", "unresolved",
    ]
    confidence: float = Field(ge=0, le=1)
    client_context_disposition: Literal[
        "not_supplied", "accepted", "overridden", "rejected",
    ]
    client_taxonomy_handle: str | None = None
    reason: str


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
    catalog_scope: CatalogScope


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

    normalized_purpose = _normal(purpose)
    # Product form factors are part of the catalog schema, not workload-name
    # aliases.  Resolve their ordinary singular wording to the canonical node
    # before the exact taxonomy-name scan (whose labels are often plural, e.g.
    # "Desktop Computers").
    form_factor_nodes = (
        (r"\bgaming laptops?\b", "el-6-11-2"),
        (r"\b(?:laptops?|notebooks?)\b", "el-6-6"),
        (r"\bdesktop(?: computers?)?\b", "el-6-3"),
        (r"\bservers?\b", "el-6-2"),
    )
    for pattern, handle in form_factor_nodes:
        if re.search(pattern, normalized_purpose):
            node = get_node(handle)
            if node is not None:
                return node

    words = normalized_purpose.split()
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
    elif preferred_handle:
        # An unrelated taxonomy label overrides storefront context only when it
        # is actually the grammatical purchase object.  A constraint such as
        # "Windows management" must not become Building Materials > Windows,
        # while "I need a standing desk" must still cross the catalog boundary.
        purpose_normal = _normal(purpose)
        purchase_objects = []
        for row in ranked:
            category = _singular(row[2].name)
            purchase_pattern = re.compile(
                rf"\b(?:need|want|buy|purchase|find|show|source|looking for|help me with)\b"
                rf"(?:\s+[a-z0-9]+){{0,8}}\s+{re.escape(category)}\b"
            )
            if purchase_pattern.search(purpose_normal):
                purchase_objects.append(row)
        if not purchase_objects:
            return None
        ranked = purchase_objects
    return max(ranked, key=lambda row: (row[0], row[1], row[2].handle))[2]


def _related(left_handle: str, right_handle: str) -> bool:
    if left_handle == right_handle:
        return True
    left_ancestors = {row.handle for row in ancestors(left_handle)}
    right_ancestors = {row.handle for row in ancestors(right_handle)}
    if left_handle in right_ancestors or right_handle in left_ancestors:
        return True
    # Shopify places Gaming Laptops outside the ordinary Laptop branch.  This
    # reviewed equivalence is deliberately narrow; treating every sibling under
    # Computers as related would leak handhelds, tablets and unrelated devices.
    laptop_family = {"el-6-6", "el-6-11-2"}
    return left_handle in laptop_family and right_handle in laptop_family


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
        return "el-6-2"
    return None


def build_case_catalog_candidate_set(
    db,
    *,
    retained_purpose: str,
    tenant_id: str,
    storefront_taxonomy_handle: str | None,
    case_id: str | None = None,
    case_revision: int | None = None,
) -> CatalogCandidateSet:
    purpose = " ".join(str(retained_purpose or "").split())[:500] or "Unresolved buyer request"
    client_handle = str(storefront_taxonomy_handle or "").strip() or None
    client_node = get_node(client_handle or "")
    client_sellable = (
        sells_within(db, client_node.handle, tenant_id=tenant_id)
        if client_node is not None else None
    )
    context_node = client_node if client_sellable is True else None
    tenant_primary_handle = primary_sold_node(db, tenant_id=tenant_id)
    tenant_primary_node = get_node(tenant_primary_handle or "")
    explicit_node = _explicit_category(
        purpose,
        preferred_handle=(
            context_node.handle if context_node is not None
            else tenant_primary_node.handle if tenant_primary_node is not None
            else None
        ),
    )

    explicit_sellable = (
        sells_within(db, explicit_node.handle, tenant_id=tenant_id)
        if explicit_node is not None else None
    )
    allowed_roots = sorted(sold_nodes(db, tenant_id=tenant_id) or [])
    requested_form_factor = str(explicit_node.name).strip() if explicit_node is not None else None

    if explicit_node is not None and explicit_sellable is not True:
        scope = CatalogScope(
            case_id=case_id,
            case_revision=case_revision,
            tenant_id=tenant_id,
            requested_product_form_factor=requested_form_factor,
            allowed_taxonomy_roots=allowed_roots,
            selected_taxonomy_root=explicit_node.handle,
            source="buyer_explicit",
            confidence=1.0,
            client_context_disposition=(
                "overridden" if client_handle else "not_supplied"
            ),
            client_taxonomy_handle=client_handle,
            reason="buyer_named_category_not_sold_by_tenant",
        )
        return CatalogCandidateSet(
            retained_purpose=purpose,
            status="out_of_category",
            taxonomy_handle=explicit_node.handle,
            taxonomy_label=explicit_node.full_path,
            taxonomy_source="explicit_query",
            reason="buyer_named_category_outside_storefront_context",
            catalog_scope=scope,
        )

    selected = explicit_node or context_node or tenant_primary_node
    source = "explicit_query" if explicit_node is not None else (
        "storefront_context" if context_node is not None else
        "storefront_context" if tenant_primary_node is not None else "unresolved"
    )
    scope_source = (
        "buyer_explicit" if explicit_node is not None else
        "validated_client_context" if context_node is not None else
        "tenant_primary" if tenant_primary_node is not None else "unresolved"
    )
    client_disposition = (
        "not_supplied" if client_handle is None else
        "accepted" if context_node is not None and explicit_node is None else
        "overridden" if explicit_node is not None else "rejected"
    )
    scope = CatalogScope(
        case_id=case_id,
        case_revision=case_revision,
        tenant_id=tenant_id,
        requested_product_form_factor=requested_form_factor,
        allowed_taxonomy_roots=allowed_roots,
        selected_taxonomy_root=selected.handle if selected is not None else None,
        source=scope_source,
        confidence=1.0 if explicit_node is not None else 0.9 if selected is not None else 0.0,
        client_context_disposition=client_disposition,
        client_taxonomy_handle=client_handle,
        reason=(
            "buyer_explicit_sellable_category" if explicit_node is not None else
            "validated_client_catalog_context" if context_node is not None else
            "tenant_grounded_primary_category" if tenant_primary_node is not None else
            "tenant_catalog_not_grounded"
        ),
    )
    if selected is None:
        return CatalogCandidateSet(
            retained_purpose=purpose,
            status="unresolved",
            taxonomy_source="unresolved",
            reason="no_product_category_or_storefront_context",
            catalog_scope=scope,
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
        catalog_scope=scope,
    )


__all__ = ["CatalogCandidateSet", "CatalogScope", "build_case_catalog_candidate_set"]
