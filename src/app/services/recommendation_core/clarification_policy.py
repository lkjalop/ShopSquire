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
) -> dict[str, Any]:
    """Return one bounded clarification after the evidence attempt is known."""
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

    for proposed in proposed_questions:
        text = str(proposed.get("question") or "").strip()
        if not text:
            continue
        return {
            "id": str(proposed.get("question_id") or "concept_resolution"),
            "goal": str(proposed.get("purpose") or "resolve_concept"),
            "reason": "unresolved_material_concept",
            "missing_slots": ["concept_resolution"],
            "text": text,
            "options": [],
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
    }
