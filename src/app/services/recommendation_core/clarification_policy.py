"""Bounded buyer-question policy for unresolved semantic evidence.

The interpreter proposes material slots and evidence needs. This module decides
which single question may be presented; it does not infer domain facts or select
products.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


def select_semantic_clarification(
    *,
    research_status: str | None,
    proposed_questions: Sequence[Mapping[str, Any]] = (),
    material_unknowns: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Return one buyer-owned question selected by expected decision impact.

    The interpreter may propose questions, but it cannot decide that a buyer is the
    authority for an unknown.  Questions tied only to research-owned unknowns are
    rejected here.  This keeps missing provider coverage from becoming a request for
    the buyer to invent hardware requirements.
    """
    status = str(research_status or "").strip().lower()
    if status == "consent_required":
        return {
            "id": "external_research_consent",
            "goal": "authorize_bounded_external_research",
            "reason": "external_research_consent_required",
            "missing_slots": ["external_research_consent"],
            "text": (
                "This request needs current external requirements before I can qualify "
                "products. May I check approved official sources?"
            ),
            "options": [
                {"id": "approve", "label": "Check approved sources", "value": "approved"},
                {"id": "decline", "label": "Do not research", "value": "declined"},
            ],
        }

    unknown_sources = {
        str(item.get("unknown_id") or "").strip():
        str(item.get("resolution_source") or "").strip().lower()
        for item in material_unknowns
        if isinstance(item, Mapping) and item.get("unknown_id")
    }
    impact_weight = {
        "architecture": 8,
        "capability": 4,
        "affordable_quantity": 2,
        "product_set": 1,
    }
    eligible: list[tuple[int, int, Mapping[str, Any], list[str], list[str]]] = []
    for index, proposed in enumerate(proposed_questions):
        text = str(proposed.get("question") or "").strip()
        if not text:
            continue
        unknown_ids = [
            str(value).strip()
            for value in list(proposed.get("resolves_unknown_ids") or [])[:4]
            if str(value).strip()
        ]
        # Legacy proposals without typed ownership remain usable only when there is
        # no typed unknown contract to contradict them.
        if unknown_sources:
            if not unknown_ids:
                continue
            if not any(unknown_sources.get(value) in {"buyer", "either"} for value in unknown_ids):
                continue
        impacts = [
            str(value).strip().lower()
            for value in list(proposed.get("decision_impacts") or [])[:4]
            if str(value).strip().lower() in impact_weight
        ]
        score = sum(impact_weight[value] for value in set(impacts))
        eligible.append((score, -index, proposed, unknown_ids, impacts))

    if eligible:
        _, _, proposed, unknown_ids, impacts = max(eligible, key=lambda item: (item[0], item[1]))
        return {
            "id": str(proposed.get("question_id") or "concept_resolution"),
            "goal": str(proposed.get("purpose") or "resolve_concept"),
            "reason": "unresolved_material_concept",
            "missing_slots": unknown_ids or ["concept_resolution"],
            "text": str(proposed.get("question") or "").strip(),
            "options": [],
            "selection_policy": "expected_decision_impact",
            "decision_impacts": impacts,
        }

    if unknown_sources and not any(
        source in {"buyer", "either"} for source in unknown_sources.values()
    ):
        return {
            "id": "authoritative_evidence_required",
            "goal": "obtain_authoritative_requirements",
            "reason": "authoritative_provider_unavailable",
            "missing_slots": list(unknown_sources)[:8],
            "text": (
                "I could not obtain approved current requirements, so I cannot qualify "
                "products yet. Provide an approved requirements document or enable an "
                "authorized source."
            ),
            "options": [],
            "selection_policy": "authority_before_catalog",
            "decision_impacts": ["capability", "product_set"],
        }

    return {
        "id": "concept_resolution",
        "goal": "resolve_concept",
        "reason": "unresolved_material_concept",
        "missing_slots": ["concept_resolution"],
        "text": (
            "What verified standard, compatibility target, or performance outcome must the "
            "product support?"
        ),
        "options": [],
        "selection_policy": "vertical_neutral_fallback",
        "decision_impacts": ["capability", "product_set"],
    }
