from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.app.services.procurement_case_state import (
    CasePatch,
    DestinationAllocation,
    MoneyConstraint,
    ProcurementCaseState,
    TemporalConstraint,
    apply_case_patch_set,
    compile_spatiotemporal_query,
    project_legacy_case_anchor,
)
from src.app.services.recommendation_core.turn_router import _bounded_case_patches


def _case() -> ProcurementCaseState:
    return ProcurementCaseState(
        case_id="case-60",
        revision=1,
        objective="Equip an engineering team for local modelling and simulation.",
        workloads=["Unreal Engine", "large CAD models", "simulation"],
        requested_quantity=60,
        budget=MoneyConstraint(amount_minor=22_000_000, currency="AUD", scope="total"),
        destinations=[
            DestinationAllocation(location_ref="Sydney", quantity=40),
            DestinationAllocation(location_ref="Perth", quantity=20),
        ],
        temporal=TemporalConstraint(
            original_expression="within four days",
            required_by="2026-08-20T17:00:00+10:00",
            timezone="Australia/Sydney",
            as_of="2026-08-16T12:00:00+10:00",
        ),
        policies={"minimum_days_cover_after_transfer": 7},
    )


def test_move_patch_changes_only_destination_allocation() -> None:
    before = _case()
    result = apply_case_patch_set(
        before,
        expected_revision=1,
        patches=[CasePatch(
            operation="move_quantity",
            path="destinations",
            quantity=5,
            from_ref="Perth",
            to_ref="Sydney",
            reason="buyer_explicit_reallocation",
        )],
    )

    after = result.state
    assert [(row.location_ref, row.quantity) for row in after.destinations] == [
        ("Sydney", 45), ("Perth", 15),
    ]
    assert after.requested_quantity == 60
    assert after.workloads == before.workloads
    assert after.budget == before.budget
    assert after.temporal == before.temporal
    assert after.revision == 2
    assert result.changed_paths == ("destinations",)


def test_patch_set_is_atomic_when_one_operation_is_invalid() -> None:
    before = _case()
    with pytest.raises(ValueError, match="destination_quantity_insufficient"):
        apply_case_patch_set(
            before,
            expected_revision=1,
            patches=[
                CasePatch(operation="set", path="budget.amount_minor", value=20_000_000),
                CasePatch(
                    operation="move_quantity", path="destinations", quantity=25,
                    from_ref="Perth", to_ref="Sydney",
                ),
            ],
        )
    assert before.budget.amount_minor == 22_000_000
    assert before.revision == 1


def test_revision_conflict_rejects_stale_multiturn_patch() -> None:
    with pytest.raises(ValueError, match="case_revision_conflict"):
        apply_case_patch_set(
            _case(), expected_revision=0,
            patches=[CasePatch(operation="set", path="requested_quantity", value=55)],
        )


def test_distribution_must_equal_total_quantity() -> None:
    with pytest.raises(ValueError, match="destination_quantity_total_mismatch"):
        apply_case_patch_set(
            _case(), expected_revision=1,
            patches=[CasePatch(operation="set", path="requested_quantity", value=59)],
        )


def test_compiler_uses_retained_case_not_latest_utterance() -> None:
    state = apply_case_patch_set(
        _case(), expected_revision=1,
        patches=[CasePatch(
            operation="move_quantity", path="destinations", quantity=5,
            from_ref="Perth", to_ref="Sydney",
        )],
    ).state

    query = compile_spatiotemporal_query(
        state,
        query_type="inventory_transfer_feasibility",
        metrics=["atp", "days_cover", "forecast_demand"],
        query_purpose="fulfilment_computation",
    )

    assert query.case_revision == 2
    assert query.workloads == ["Unreal Engine", "large CAD models", "simulation"]
    assert [(row.location_ref, row.quantity) for row in query.destinations] == [
        ("Sydney", 45), ("Perth", 15),
    ]
    assert query.requested_quantity == 60
    assert query.required_by == datetime(2026, 8, 20, 7, 0, tzinfo=timezone.utc)
    assert query.as_of == datetime(2026, 8, 16, 2, 0, tzinfo=timezone.utc)
    assert query.constraints["minimum_days_cover_after_transfer"] == 7
    assert query.allowed_dimensions == ["spatial", "temporal", "commercial", "inventory"]
    assert query.external_research_authorized is False


def test_workload_discovery_query_excludes_destination_but_logistics_keeps_it() -> None:
    state = _case().model_copy(update={
        "workloads": ["HEC-RAS 2D flood modelling", "drone photogrammetry"],
        "destinations": [DestinationAllocation(location_ref="Cairns", quantity=18)],
        "requested_quantity": 18,
    })

    workload = compile_spatiotemporal_query(
        state,
        query_type="authoritative_requirement_discovery",
        query_purpose="workload_discovery",
        metrics=["software_requirements"],
    )
    logistics = compile_spatiotemporal_query(
        state,
        query_type="delivery_feasibility",
        query_purpose="logistics_discovery",
        metrics=["carrier_service", "arrival_probability"],
    )

    assert workload.search_dimensions == {"semantic": state.workloads}
    assert "spatial" in workload.prohibited_dimensions
    assert logistics.search_dimensions["spatial"] == ["Cairns"]
    assert "spatial" in logistics.allowed_dimensions


def test_unknown_or_unresolved_time_never_becomes_a_promise() -> None:
    state = _case().model_copy(update={
        "temporal": TemporalConstraint(
            original_expression="next Thursday",
            timezone="Australia/Sydney",
            as_of="2026-08-16T12:00:00+10:00",
        )
    })
    query = compile_spatiotemporal_query(
        state, query_type="delivery_feasibility", query_purpose="fulfilment_computation",
        metrics=["arrival_probability"],
    )
    assert query.required_by is None
    assert "required_by" in query.unresolved_fields
    assert query.promise_authority == "none"


def test_legacy_anchor_projection_preserves_compatibility() -> None:
    projected = project_legacy_case_anchor({
        "case_id": "legacy-1",
        "quantity": 12,
        "destination": "Sydney",
        "deadline": "2026-08-20T17:00:00+10:00",
        "budget": {"total_cents": 6_000_000, "currency": "AUD", "scope": "total"},
        "semantic_resolution": {"hypotheses": [{"label": "CAD"}]},
    })

    assert projected.case_id == "legacy-1"
    assert projected.requested_quantity == 12
    assert projected.destinations[0].location_ref == "Sydney"
    assert projected.workloads == ["CAD"]
    assert projected.budget.amount_minor == 6_000_000


def test_model_case_patch_must_be_grounded_in_current_buyer_turn() -> None:
    data = {
        "case_patches": [
            {
                "operation": "move_quantity", "path": "destinations",
                "quantity": 5, "from_ref": "Perth", "to_ref": "Sydney",
            },
            {
                "operation": "set", "path": "destinations",
                "value": [{"location_ref": "Cairn", "quantity": 18}],
            },
        ]
    }
    accepted = _bounded_case_patches(
        data, "Reduce Perth by 5 and move those units to Sydney. Keep total 60."
    )

    assert len(accepted) == 1
    assert accepted[0]["operation"] == "move_quantity"
    assert accepted[0]["from_ref"] == "Perth"


def test_model_can_propose_explicit_multi_destination_allocation_without_keyword_rules() -> None:
    accepted = _bounded_case_patches({
        "case_patches": [{
            "operation": "set", "path": "destinations",
            "value": [
                {"location_ref": "Sydney", "quantity": 40},
                {"location_ref": "Perth", "quantity": 20},
            ],
        }]
    }, "We need 60 laptops: 40 to Sydney and 20 to Perth.")

    assert accepted == ({
        "operation": "set", "path": "destinations",
        "value": [
            {"location_ref": "Sydney", "quantity": 40},
            {"location_ref": "Perth", "quantity": 20},
        ],
    },)
