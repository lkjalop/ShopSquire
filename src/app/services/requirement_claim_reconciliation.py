"""Reconcile buyer-supplied constraints with scoped official requirement claims.

Official evidence may corroborate or contradict a buyer claim, but a weaker
publisher floor never silently authorizes the buyer's stronger sizing choice.
"""
from __future__ import annotations

from typing import Any, Literal, Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field


ReconciliationStatus = Literal[
    "corroborated", "contradicted", "unresolved", "preference_only",
]


class ReconciledRequirementClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    buyer_claim_id: str
    attribute: str
    status: ReconciliationStatus
    official_claim_ids: list[str] = Field(default_factory=list, max_length=16)
    reason: str


def _values(value: Any) -> set[str]:
    rows = value if isinstance(value, list) else [value]
    return {str(item).strip().casefold() for item in rows if item is not None}


def _numeric(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _compare(
    buyer: Mapping[str, Any], official: Sequence[Mapping[str, Any]],
) -> tuple[ReconciliationStatus, str]:
    requirement_class = str(buyer.get("requirement_class") or "minimum")
    preference = requirement_class in {"recommended", "target", "optimal", "preferred"}
    if not official:
        return (
            ("preference_only", "No official requirement establishes this buyer preference.")
            if preference else
            ("unresolved", "No applicable official claim establishes or contradicts this requirement.")
        )
    buyer_operator = str(buyer.get("operator") or "=")
    buyer_number = _numeric(buyer.get("value"))
    if buyer_operator == ">=" and buyer_number is not None:
        official_floors = [
            value for row in official
            if str(row.get("operator") or "=") == ">="
            and (value := _numeric(row.get("value"))) is not None
        ]
        if official_floors and max(official_floors) >= buyer_number:
            return "corroborated", "An applicable official floor is at least as strict as this requirement."
        if official_floors:
            return (
                "preference_only" if preference else "unresolved",
                "Official evidence establishes a weaker floor, not this stronger sizing choice.",
            )
    buyer_values = _values(buyer.get("value"))
    official_values = set().union(*(_values(row.get("value")) for row in official))
    if buyer_values and official_values:
        if buyer_values <= official_values or (
            buyer_operator == "one_of" and buyer_values & official_values
        ):
            return "corroborated", "The accepted value is included in the applicable official requirement."
        return "contradicted", "Applicable official evidence conflicts with the accepted value."
    return (
        "preference_only" if preference else "unresolved",
        "The official claim is related but does not establish this exact constraint.",
    )


def reconcile_requirement_claims(
    buyer_claims: Sequence[Mapping[str, Any]],
    official_claims: Sequence[Mapping[str, Any]],
) -> list[ReconciledRequirementClaim]:
    """Return one exhaustive, deterministic status for every accepted buyer claim."""

    official_by_attribute: dict[str, list[Mapping[str, Any]]] = {}
    for claim in official_claims:
        attribute = str(claim.get("attribute") or "").strip()
        if attribute:
            official_by_attribute.setdefault(attribute, []).append(claim)
    rows: list[ReconciledRequirementClaim] = []
    for claim in buyer_claims:
        claim_id = str(claim.get("claim_id") or "").strip()
        attribute = str(claim.get("attribute") or "").strip()
        matches = official_by_attribute.get(attribute, [])
        status, reason = _compare(claim, matches)
        rows.append(ReconciledRequirementClaim(
            buyer_claim_id=claim_id,
            attribute=attribute,
            status=status,
            official_claim_ids=[
                str(item.get("claim_id")) for item in matches if item.get("claim_id")
            ],
            reason=reason,
        ))
    return rows


__all__ = ["ReconciledRequirementClaim", "reconcile_requirement_claims"]
