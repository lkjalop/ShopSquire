"""Reconcile later authoritative research with the earlier semantic decision.

The recommendation router necessarily runs before external research.  This
reducer binds provider evidence back to the exact buyer-authored concept that
caused research, then derives terminal semantic authority without rerunning the
model or the complete recommendation core.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping


_TOKEN = re.compile(r"[a-z0-9]+")


def _normal(value: object) -> str:
    return " ".join(_TOKEN.findall(str(value or "").casefold()))


def _phrase_in(value: object, phrase: str) -> bool:
    normalized = _normal(value)
    return bool(phrase and (
        normalized == phrase
        or f" {phrase} " in f" {normalized} "
    ))


def reconcile_workload_questions(
    questions: list[dict[str, Any]], authorization: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    """Retire only provider-answered obligations, never buyer preferences.

    Unbound legacy questions remain unresolved: prose is not an identity key.
    A combined obligation remains until every bound workload has evidence.
    """
    resolved = {
        _normal(row.get("requested_name"))
        for row in (authorization or {}).get("evidence", [])
        if isinstance(row, Mapping) and row.get("status") == "resolved"
        and row.get("compiled_requirements") and row.get("source_url")
    } - {""}
    return [question for question in questions if not (
        question.get("goal") == "resolve_named_workload"
        and question.get("workload_subjects")
        and {_normal(name) for name in question["workload_subjects"]} <= resolved
    )]


@dataclass(frozen=True)
class SemanticResearchReconciliation:
    semantic_resolution: dict[str, Any]
    resolved_concept_spans: tuple[str, ...]
    requirements_established: bool


@dataclass(frozen=True)
class TerminalCatalogGate:
    """Revision-terminal catalog projection after research has completed.

    Identity confirmation is an authority boundary, not merely a narration
    state.  Keeping pre-research catalog candidates in the terminal payload
    would let the UI display products that the same outcome says cannot yet be
    qualified.
    """

    products: tuple[dict[str, Any], ...]
    product_shelves: dict[str, Any] | None
    catalog_authority: str

    @property
    def recommendation_status(self) -> str:
        if self.catalog_authority == "blocked":
            return "blocked"
        if self.catalog_authority != "permitted":
            return "held"
        from src.app.services.terminal_qualification import shelf_products
        has_matches = any(
            item.get('fit_status') == 'qualified'
            for item in shelf_products(self.product_shelves)
        )
        return "qualified" if has_matches else "no_qualified_products"


def gate_terminal_catalog_projection(
    *,
    research_status: object,
    products: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None,
    product_shelves: Mapping[str, Any] | None,
    catalog_authority: object,
    requirement_completeness: object = None,
) -> TerminalCatalogGate:
    status = str(research_status or "").strip().lower()
    authority = str(catalog_authority or "unknown").strip().lower() or "unknown"
    if authority == 'unknown' and status != 'identity_confirmation_required':
        return TerminalCatalogGate(products=(), product_shelves=None, catalog_authority='unknown')
    if (status == "identity_confirmation_required" or authority == "blocked"
            or (authority == "permitted"
                and str(requirement_completeness or "").lower() == "partial")):
        return TerminalCatalogGate(
            products=(),
            product_shelves=None,
            catalog_authority="blocked",
        )
    return TerminalCatalogGate(
        products=tuple(dict(row) for row in list(products or []) if isinstance(row, Mapping)),
        product_shelves=(dict(product_shelves) if isinstance(product_shelves, Mapping) else None),
        catalog_authority=authority,
    )


def reconcile_semantic_resolution(
    semantic_resolution: Mapping[str, Any] | None,
    workload_authorization: Mapping[str, Any] | None,
    *,
    buyer_text: object = None,
) -> SemanticResearchReconciliation:
    """Bind resolved provider evidence to its exact originating concept.

    A provider result cannot globally erase uncertainty.  It releases catalog
    authority only when it has compiled requirements and its ``requested_name``
    exactly matches a material concept anchor from this turn.
    """

    semantic = dict(semantic_resolution or {})
    authorization = dict(workload_authorization or {})
    evidence_rows = [
        dict(row) for row in list(authorization.get("evidence") or [])
        if isinstance(row, Mapping)
        and str(row.get("status") or "").strip().lower() == "resolved"
        and bool(row.get("compiled_requirements"))
        and bool(row.get("source_url") or row.get("source"))
    ]
    requested = {
        _normal(row.get("requested_name")): row
        for row in evidence_rows if _normal(row.get("requested_name"))
    }

    resolved_spans: list[str] = []
    concepts: list[dict[str, Any]] = []
    for raw in list(semantic.get("concepts") or []):
        if not isinstance(raw, Mapping):
            continue
        concept = dict(raw)
        anchor = _normal(concept.get("query_span") or concept.get("text"))
        bound_key = next((
            name for name in requested
            if anchor == name or _phrase_in(anchor, name)
        ), None)
        bound = requested.get(bound_key) if bound_key else None
        if bound is not None:
            concept.update({
                "status": "resolved",
                "resolution_source": "enrolled_structured_provider",
                "resolved_identity": (
                    bound.get("canonical_title") or bound.get("resolved_name")
                ),
                "source_url": bound.get("source_url"),
            })
            # Record the provider-bound identity rather than trailing buyer
            # targets (for example ``at 1080p``).  This lets the same exact
            # identity resolve its research-owned requirement obligation while
            # leaving unrelated buyer-owned unknowns untouched.
            resolved_spans.append(str(bound_key))
        concepts.append(concept)

    # A timed-out/degraded router can legitimately emit no semantic concepts.
    # Later structured-provider evidence may still be authoritative, but only
    # bind it when its requested identity is literally present in the buyer's
    # turn. This recovers newer truth without granting a provider permission to
    # resolve an unrelated or inferred subject.
    if not concepts and not list(semantic.get("material_unknowns") or []):
        buyer_anchor = _normal(buyer_text)
        for requested_name in requested:
            if _phrase_in(buyer_anchor, requested_name):
                resolved_spans.append(requested_name)

    unknowns: list[dict[str, Any]] = []
    for raw in list(semantic.get("material_unknowns") or []):
        if not isinstance(raw, Mapping):
            continue
        unknown = dict(raw)
        resolution_owner = str(
            unknown.get("resolution_source") or ""
        ).strip().lower()
        matched = next((
            span for span in resolved_spans
            if resolution_owner in {"research", "either"}
            and _phrase_in(unknown.get("description"), span)
        ), None)
        if matched:
            unknown.update({
                "status": "resolved",
                "resolved_by": "enrolled_structured_provider",
                "resolved_concept_span": matched,
            })
        unknowns.append(unknown)

    unresolved_concepts = [
        row for row in concepts
        if bool(row.get("material", True))
        and str(row.get("status") or "unresolved").lower() != "resolved"
    ]
    unresolved_unknowns = [
        row for row in unknowns
        if bool(row.get("material", True))
        and str(row.get("status") or "unresolved").lower() != "resolved"
    ]
    requirements_established = bool(resolved_spans and evidence_rows)
    semantic["concepts"] = concepts
    semantic["material_unknowns"] = unknowns
    semantic["research_reconciliation"] = {
        "status": "resolved" if requirements_established else "not_bound",
        "resolved_concept_spans": list(resolved_spans),
        "provider_evidence_count": len(evidence_rows),
    }

    if requirements_established and not unresolved_concepts and not unresolved_unknowns:
        semantic.update({
            "outcome": "proceed_catalog",
            "catalog_authority": "permitted",
            "reasons": ["material_concepts_resolved_by_provider"],
            "questions": [],
            "state_prevented": [],
            "next_permitted_action": "align_catalog",
            "residual_route": "CONNECTOR",
            "residual_reasons": ["authoritative_catalog_fact_required"],
            "authorization_granted": False,
        })
    elif requirements_established:
        semantic.update({
            "outcome": "clarify",
            "catalog_authority": "blocked",
            "reasons": ["remaining_material_unknowns"],
            "next_permitted_action": "ask_material_clarification",
        })

    return SemanticResearchReconciliation(
        semantic_resolution=semantic,
        resolved_concept_spans=tuple(resolved_spans),
        requirements_established=requirements_established,
    )


__all__ = [
    "SemanticResearchReconciliation",
    "TerminalCatalogGate",
    "gate_terminal_catalog_projection",
    "reconcile_semantic_resolution",
]
