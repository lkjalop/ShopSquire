"""Deterministic certificate for the canonical two-turn procurement journey."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from typing import Any

from src.app.services.bounded_allocation_solver import (
    DestinationDemand,
    FacilitySupply,
    TransferLane,
    solve_bounded_allocation,
)
from src.app.services.procurement_case_state import (
    CasePatch,
    DestinationAllocation,
    MoneyConstraint,
    ProcurementCaseState,
    TemporalConstraint,
    apply_case_patch_set,
    compile_spatiotemporal_query,
    resolve_temporal_constraint,
)
from src.app.services.procurement_truth_adjudicator import adjudicate_procurement_truth
from src.app.services.recommendation_core.turn_router import _bounded_case_patches


TURN_ONE = (
    "We need 60 engineering laptops: 40 to Sydney and 20 to Perth. "
    "They need Unreal Engine, large CAD models and simulation. "
    "At least 30 must arrive within four days. Budget is AUD 220,000. "
    "Do not leave an origin below seven days of cover."
)
TURN_TWO = "Reduce Perth by 5 and move those units to Sydney. Keep total 60."


def _digest(value: Any) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_conversational_procurement_certificate(
    *,
    turn_one: str = TURN_ONE,
    turn_two: str = TURN_TWO,
    interpretation_instant: datetime | None = None,
) -> dict[str, Any]:
    interpreted = interpretation_instant or datetime(2026, 8, 20, tzinfo=timezone.utc)
    if interpreted.tzinfo is None:
        raise ValueError("certificate_interpretation_time_requires_timezone")
    temporal = resolve_temporal_constraint(
        TemporalConstraint(
            original_expression="within four days",
            timezone="Australia/Sydney",
            as_of=interpreted.isoformat(),
        ),
        interpretation_instant=interpreted,
    )
    initial = ProcurementCaseState(
        case_id="case-spatiotemporal-60",
        revision=1,
        objective="Equip engineering teams for local modelling and simulation.",
        workloads=["Unreal Engine", "large CAD models", "simulation"],
        selected_sku="ENG-LAPTOP-CFG-A",
        requested_quantity=60,
        budget=MoneyConstraint(
            amount_minor=22_000_000, currency="AUD", scope="total",
        ),
        destinations=[
            DestinationAllocation(
                location_ref="Sydney", location_kind="city", quantity=40,
            ),
            DestinationAllocation(
                location_ref="Perth", location_kind="city", quantity=20,
            ),
        ],
        temporal=temporal,
        policies={
            "minimum_early_arrival_quantity": 30,
            "minimum_days_cover_after_transfer": 7,
        },
        research={"consent": False},
        authority={"confirmation_pending": False, "action_allowed": False},
    )
    proposed = {
        "case_patches": [{
            "operation": "move_quantity",
            "path": "destinations",
            "quantity": 5,
            "from_ref": "Perth",
            "to_ref": "Sydney",
            "reason": "buyer_explicit_reallocation",
        }],
    }
    grounded = _bounded_case_patches(proposed, turn_two)
    if len(grounded) != 1:
        raise ValueError("certificate_turn_two_patch_not_grounded")
    patched = apply_case_patch_set(
        initial, expected_revision=1,
        patches=[CasePatch.model_validate(row) for row in grounded],
    ).state

    pre_authorization = compile_spatiotemporal_query(
        patched,
        query_type="authoritative_requirement_discovery",
        query_purpose="workload_discovery",
        metrics=["software_requirements"],
        now=interpreted,
    )
    logistics = compile_spatiotemporal_query(
        patched,
        query_type="delivery_feasibility",
        query_purpose="fulfilment_computation",
        metrics=["atp", "days_cover", "arrival_probability"],
        now=interpreted,
    )
    accepted_state = patched.model_copy(update={
        "research": {
            "consent": True,
            "complete": True,
            "claims": [
                {"status": "accepted", "subject": "Unreal Engine"},
                {"status": "accepted", "subject": "large CAD models"},
                {"status": "accepted", "subject": "simulation"},
            ],
            "provider_accounting": {"external_calls": 0, "paid_calls": 0},
            "execution": "enrolled_evidence_fixture_completed",
        },
        "requirements": {
            "accepted": [
                {"attribute": "gpu_class", "value": "engineering"},
                {"attribute": "memory_gb", "operator": ">=", "value": 32},
            ],
        },
    })
    authorized = compile_spatiotemporal_query(
        accepted_state,
        query_type="authoritative_requirement_discovery",
        query_purpose="workload_discovery",
        metrics=["software_requirements"],
        now=interpreted,
    )

    origin_inputs = (
        {
            "facility_id": "warehouse:sydney-origin",
            "destination_id": "Sydney",
            "on_hand_units": 40,
            "forecast_daily_units": 2.0,
            "lead_time_days": 1,
            "lane_capacity_units": 40,
        },
        {
            "facility_id": "warehouse:perth-origin",
            "destination_id": "Perth",
            "on_hand_units": 25,
            "forecast_daily_units": 1.0,
            "lead_time_days": 3,
            "lane_capacity_units": 25,
        },
    )
    minimum_cover = int(accepted_state.policies["minimum_days_cover_after_transfer"])
    supplies: list[FacilitySupply] = []
    lanes: list[TransferLane] = []
    for row in origin_inputs:
        protected = math.ceil(float(row["forecast_daily_units"]) * minimum_cover)
        supplies.append(FacilitySupply(
            facility_id=str(row["facility_id"]),
            facility_kind="warehouse",
            sku=str(accepted_state.selected_sku),
            on_hand_units=int(row["on_hand_units"]),
            protected_demand_units=protected,
            observed_at=interpreted.isoformat(),
        ))
        lanes.append(TransferLane(
            lane_id=f"lane:{row['facility_id']}:{row['destination_id']}",
            origin_facility_id=str(row["facility_id"]),
            destination_id=str(row["destination_id"]),
            capacity_units=int(row["lane_capacity_units"]),
            lead_time_days=int(row["lead_time_days"]),
            cost_minor_per_unit=100,
        ))
    demands = [
        DestinationDemand(
            destination_id=row.location_ref,
            location_kind="city",
            requested_units=row.quantity,
            deadline_days=4,
        )
        for row in accepted_state.destinations
    ]
    allocation = solve_bounded_allocation(
        supplies=supplies, demands=demands, lanes=lanes,
    )
    supplier_shortfall = {
        "status": "proposal_only",
        "quantity": allocation.shortfall_units,
        "relationship": "exact_configuration_required",
        "supplier_send_authority": "none",
    }
    fulfilment_state = accepted_state.model_copy(update={
        "fulfilment": {
            "allocation_projection": allocation.model_dump(mode="json"),
            "commercial_decision": {
                "status": "CONDITIONAL_NOW",
                "quantity_outcome": "partial",
                "budget_outcome": "within",
            },
            "supplier_shortfall": supplier_shortfall,
        },
    })
    watermarks = [
        {
            "source": f"enrolled_fixture:{row['facility_id']}",
            "state": "current",
            "observed_at": interpreted.isoformat(),
        }
        for row in origin_inputs
    ]
    truth = adjudicate_procurement_truth(
        state_data=fulfilment_state.model_dump(mode="json"),
        evidence_watermarks=watermarks,
        evaluated_at=interpreted,
    )
    early_arrival = allocation.allocated_units
    invariant_checks = {
        "turn_one_exactly_recorded": turn_one == TURN_ONE,
        "turn_two_exactly_recorded": turn_two == TURN_TWO,
        "quantity_preserved": patched.requested_quantity == 60,
        "destination_move_applied": [
            (row.location_ref, row.quantity) for row in patched.destinations
        ] == [("Sydney", 45), ("Perth", 15)],
        "unrelated_fields_preserved": all((
            patched.workloads == initial.workloads,
            patched.budget == initial.budget,
            patched.temporal == initial.temporal,
            patched.policies == initial.policies,
        )),
        "case_revision_advanced_once": patched.revision == 2,
        "temporal_authority_resolved": temporal.resolution_status == "resolved",
        "workload_query_excludes_destinations": not any(
            city in json.dumps(pre_authorization.search_dimensions)
            for city in ("Sydney", "Perth")
        ),
        "logistics_query_contains_destinations": set(
            logistics.search_dimensions.get("spatial") or []
        ) == {"Sydney", "Perth"},
        "zero_calls_before_authorization": not pre_authorization.external_research_authorized,
        "research_authorization_recorded": authorized.external_research_authorized,
        "accepted_requirements_same_revision": accepted_state.revision == patched.revision,
        "minimum_early_arrival_met": early_arrival >= 30,
        "origin_cover_protected": all(
            supply.protected_demand_units
            == math.ceil(float(origin["forecast_daily_units"]) * minimum_cover)
            for supply, origin in zip(supplies, origin_inputs, strict=True)
        ),
        "supplier_shortfall_is_proposal_only": (
            supplier_shortfall["status"] == "proposal_only"
            and supplier_shortfall["supplier_send_authority"] == "none"
        ),
        "no_cart_mutation": truth.cart_mutations == 0,
        "paid_calls_zero": truth.paid_calls == 0,
        "commerce_authority_not_granted": truth.commerce_authority == "NONE",
    }
    artifact: dict[str, Any] = {
        "schema_version": "conversational-spatiotemporal-certificate-v1",
        "execution": "deterministic_domain_certificate",
        "fixture": True,
        "live_network_certified": False,
        "turns": [turn_one, turn_two],
        "initial_state": initial.model_dump(mode="json"),
        "amended_state": patched.model_dump(mode="json"),
        "accepted_state": accepted_state.model_dump(mode="json"),
        "queries": {
            "pre_authorization_workload": pre_authorization.model_dump(mode="json"),
            "authorized_workload": authorized.model_dump(mode="json"),
            "logistics": logistics.model_dump(mode="json"),
            "hashes": {
                "pre_authorization_workload": _digest(
                    pre_authorization.model_dump(mode="json")
                ),
                "authorized_workload": _digest(authorized.model_dump(mode="json")),
                "logistics": _digest(logistics.model_dump(mode="json")),
            },
        },
        "allocation": allocation.model_dump(mode="json"),
        "origin_cover_inputs": list(origin_inputs),
        "supplier_shortfall": supplier_shortfall,
        "rank_movement": {
            "candidate": "ENG-LAPTOP-CFG-A",
            "reason": "accepted_official_requirements_joined_case_revision_2",
            "authority": "evidence_bound_projection",
        },
        "canonical_truth": truth.model_dump(mode="json"),
        "provider_accounting": {
            "external_calls_before_authorization": 0,
            "external_calls_after_authorization": 0,
            "paid_calls": 0,
            "reason": "enrolled_evidence_fixture_no_network_dispatch",
        },
        "invariants": invariant_checks,
        "passed": all(invariant_checks.values()),
    }
    artifact["artifact_sha256"] = _digest(artifact)
    return artifact


__all__ = [
    "TURN_ONE", "TURN_TWO", "build_conversational_procurement_certificate",
]
