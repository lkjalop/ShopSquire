"""Independent allocation rankings with explicit disagreement and evidence gaps."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from src.app.services.bounded_allocation_solver import AllocationPlan


class AllocationCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate_id: str = Field(min_length=1, max_length=120)
    plan: AllocationPlan
    minimum_post_allocation_cover_days: float | None = Field(default=None, ge=0)
    supplier_risk_score: float | None = Field(default=None, ge=0, le=1)
    observation_refs: tuple[str, ...] = ()


def _rank(candidates: list[AllocationCandidate], key, *, reverse: bool = False) -> list[str]:
    eligible = [row for row in candidates if key(row) is not None]
    return [
        row.candidate_id for row in sorted(
            eligible, key=lambda row: (key(row), row.candidate_id), reverse=reverse,
        )
    ]


def arbitrate_allocation_conflict(
    candidates: list[AllocationCandidate],
    *,
    minimum_cover_days: float,
    maximum_supplier_risk: float,
) -> dict[str, Any]:
    """Rank each objective separately; recommend only after deterministic criticism."""

    if len(candidates) < 2:
        raise ValueError("allocation_arbitration_requires_multiple_candidates")
    ids = [row.candidate_id for row in candidates]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate_allocation_candidate")
    rankings = {
        "cost": _rank(candidates, lambda row: row.plan.total_transfer_cost_minor),
        "deadline": _rank(
            candidates,
            lambda row: max((line.lead_time_days for line in row.plan.lines), default=10**9),
        ),
        "stock_cover": _rank(
            candidates, lambda row: row.minimum_post_allocation_cover_days, reverse=True,
        ),
        "supplier_risk": _rank(candidates, lambda row: row.supplier_risk_score),
    }
    winners = {name: rows[0] for name, rows in rankings.items() if rows}
    disagreements = [
        {"criterion": criterion, "winner": winner}
        for criterion, winner in winners.items()
        if len(set(winners.values())) > 1
    ]
    evidence_requests: list[dict[str, str]] = []
    for row in candidates:
        if row.minimum_post_allocation_cover_days is None:
            evidence_requests.append({
                "candidate_id": row.candidate_id,
                "field": "minimum_post_allocation_cover_days",
                "purpose": "resolve_stock_cover_ranking",
            })
        if row.supplier_risk_score is None:
            evidence_requests.append({
                "candidate_id": row.candidate_id,
                "field": "supplier_risk_score",
                "purpose": "resolve_supplier_risk_ranking",
            })
        if not row.observation_refs:
            evidence_requests.append({
                "candidate_id": row.candidate_id,
                "field": "observation_refs",
                "purpose": "bind_plan_to_revisioned_observations",
            })
    critic_rows = []
    for row in candidates:
        reasons: list[str] = []
        if row.plan.status != "complete":
            reasons.append("allocation_incomplete")
        if (
            row.minimum_post_allocation_cover_days is None
            or row.minimum_post_allocation_cover_days < minimum_cover_days
        ):
            reasons.append("stock_cover_unknown_or_below_minimum")
        if row.supplier_risk_score is None or row.supplier_risk_score > maximum_supplier_risk:
            reasons.append("supplier_risk_unknown_or_above_maximum")
        if not row.observation_refs:
            reasons.append("revision_bound_observations_missing")
        critic_rows.append({
            "candidate_id": row.candidate_id,
            "status": "accepted" if not reasons else "rejected",
            "reasons": reasons,
        })
    accepted = {
        row["candidate_id"] for row in critic_rows if row["status"] == "accepted"
    }
    recommendation = next(
        (candidate_id for candidate_id in rankings["cost"] if candidate_id in accepted),
        None,
    )
    return {
        "schema_version": "allocation-conflict-arbitration.v1",
        "candidate_count": len(candidates),
        "independent_rankings": rankings,
        "criterion_winners": winners,
        "disagreements": disagreements,
        "evidence_requests": evidence_requests,
        "deterministic_critic": critic_rows,
        "recommendation": recommendation,
        "decision_status": (
            "recommended_with_visible_conflict" if recommendation and disagreements
            else "recommended" if recommendation
            else "blocked_missing_or_failed_evidence"
        ),
        "authority": "advisory_only",
        "reservation_allowed": False,
        "supplier_send_allowed": False,
        "purchase_allowed": False,
    }


__all__ = ["AllocationCandidate", "arbitrate_allocation_conflict"]
