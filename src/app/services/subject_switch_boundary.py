"""Deterministic state boundary for buyer subject replacement turns."""
from __future__ import annotations

from typing import Any, MutableMapping


_SUBJECT_SCOPED_KEYS = (
    "canonical_case",
    "external_research_consent",
    "workload_authorization",
    "workload_evidence",
    "research_plan",
    "research_state",
    "accepted_requirements",
    "selected_product",
    "prior_shortlist",
)


def clear_subject_scoped_state(
    state: MutableMapping[str, Any], *, retain_same_turn_consent: bool = False,
) -> dict[str, Any]:
    """Remove inherited semantic authority while preserving shared constraints.

    Budget, currency, quantity and destination fields are deliberately not in
    ``_SUBJECT_SCOPED_KEYS``.  They may be shared procurement constraints; the
    new subject still has to re-establish workload evidence and authority.
    """

    cleared: list[str] = []
    for key in _SUBJECT_SCOPED_KEYS:
        if key == "external_research_consent" and retain_same_turn_consent:
            continue
        if key in state:
            state.pop(key, None)
            cleared.append(key)
    return {
        "schema_version": "subject-switch-boundary-v1",
        "cleared_fields": cleared,
        "retained_shared_fields": sorted(
            key for key in state
            if key in {"budget_min", "budget_max", "currency", "requested_quantity", "destinations"}
        ),
        "research_authority": (
            "granted_on_replacement_turn"
            if retain_same_turn_consent else "required"
        ),
        "commerce_authority": "none",
    }


__all__ = ["clear_subject_scoped_state"]
