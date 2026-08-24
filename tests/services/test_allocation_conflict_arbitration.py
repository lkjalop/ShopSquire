from src.app.services.allocation_conflict_arbitration import (
    AllocationCandidate,
    arbitrate_allocation_conflict,
)
from src.app.services.bounded_allocation_solver import (
    AllocationLine,
    AllocationPlan,
)


def _candidate(
    candidate_id: str, *, cost: int, lead: int, cover: float | None,
    risk: float | None, refs: tuple[str, ...] = ("obs-1@rev-7",),
) -> AllocationCandidate:
    return AllocationCandidate(
        candidate_id=candidate_id,
        plan=AllocationPlan(
            status="complete", requested_units=10, allocated_units=10,
            shortfall_units=0, total_transfer_cost_minor=cost,
            protected_units_by_facility={"origin": 5}, reasons=(),
            lines=(AllocationLine(
                facility_id="origin", facility_kind="warehouse", destination_id="dest",
                lane_id=f"lane-{candidate_id}", sku="SKU-1", quantity=10,
                lead_time_days=lead, cost_minor=cost,
            ),),
        ),
        minimum_post_allocation_cover_days=cover,
        supplier_risk_score=risk,
        observation_refs=refs,
    )


def test_arbitration_preserves_conflict_and_asks_only_for_missing_evidence() -> None:
    result = arbitrate_allocation_conflict([
        _candidate("cheap", cost=100, lead=4, cover=8, risk=0.3),
        _candidate("fast", cost=180, lead=1, cover=10, risk=0.1),
        _candidate("unknown", cost=140, lead=2, cover=None, risk=None, refs=()),
    ], minimum_cover_days=7, maximum_supplier_risk=0.4)

    assert result["criterion_winners"] == {
        "cost": "cheap", "deadline": "fast", "stock_cover": "fast",
        "supplier_risk": "fast",
    }
    assert result["recommendation"] == "cheap"
    assert result["decision_status"] == "recommended_with_visible_conflict"
    assert {row["field"] for row in result["evidence_requests"]} == {
        "minimum_post_allocation_cover_days", "supplier_risk_score", "observation_refs",
    }
    assert result["reservation_allowed"] is False
    assert result["supplier_send_allowed"] is False
