from datetime import datetime, timezone

from src.app.services.promise_critic import critique_promise
from src.app.services.promise_feasibility import evaluate_critical_path, evaluate_promise_feasibility


DEADLINE = datetime(2026, 8, 11, 7, 0, tzinfo=timezone.utc)


def test_missing_arrival_evidence_is_unknown_not_deadline_met() -> None:
    result = evaluate_promise_feasibility(
        requested_quantity=80,
        requested_arrival_at=DEADLINE,
        evaluated_at=datetime(2026, 8, 8, tzinfo=timezone.utc),
        supply_lines=[
            {"source_ref": "SYD", "quantity": 8, "status": "confirmed", "arrival_max": None},
            {"source_ref": "MEL", "quantity": 45, "status": "confirmed", "arrival_max": None},
            {"source_ref": "SUP", "quantity": 27, "status": "unconfirmed"},
        ],
        dependency_versions={"atp": "atp-7", "calendar": "calendar-v3"},
    )

    assert result["feasibility"] == "unknown"
    assert result["quantity_confirmed_by_deadline"] == 0
    assert result["unknown_quantity"] == 80
    assert "arrival_evidence_missing" in result["reason_codes"]


def test_partial_confirmed_supply_never_becomes_full_promise() -> None:
    result = evaluate_promise_feasibility(
        requested_quantity=80,
        requested_arrival_at=DEADLINE,
        evaluated_at=datetime(2026, 8, 8, tzinfo=timezone.utc),
        supply_lines=[
            {"source_ref": "SYD", "quantity": 8, "status": "confirmed",
             "arrival_max": "2026-08-11T03:00:00Z"},
            {"source_ref": "MEL", "quantity": 45, "status": "confirmed",
             "arrival_max": "2026-08-11T06:00:00Z"},
            {"source_ref": "SUP", "quantity": 27, "status": "unconfirmed",
             "arrival_min": "2026-08-11T04:00:00Z", "arrival_max": "2026-08-11T07:00:00Z"},
        ],
        dependency_versions={"atp": "atp-7", "calendar": "calendar-v3"},
    )

    assert result["feasibility"] == "unknown"
    assert result["quantity_confirmed_by_deadline"] == 53
    assert result["unknown_quantity"] == 27
    assert result["state_prevented"] == "unsupported_full_delivery_promise"


def test_missed_latest_response_time_makes_full_request_infeasible() -> None:
    result = evaluate_promise_feasibility(
        requested_quantity=80,
        requested_arrival_at=DEADLINE,
        evaluated_at=datetime(2026, 8, 11, 3, 1, tzinfo=timezone.utc),
        latest_viable_response_at=datetime(2026, 8, 11, 3, 0, tzinfo=timezone.utc),
        supply_lines=[
            {"source_ref": "NETWORK", "quantity": 53, "status": "confirmed",
             "arrival_max": "2026-08-11T06:00:00Z"},
            {"source_ref": "SUP", "quantity": 27, "status": "unconfirmed",
             "arrival_max": "2026-08-11T07:00:00Z"},
        ],
        dependency_versions={"cutoff": "carrier-13h-v1"},
    )

    assert result["feasibility"] == "missed"
    assert "latest_viable_response_elapsed" in result["reason_codes"]


def test_promise_critic_blocks_full_promise_and_full_capture_on_unknown_supply() -> None:
    feasibility = evaluate_promise_feasibility(
        requested_quantity=80,
        requested_arrival_at=DEADLINE,
        evaluated_at=datetime(2026, 8, 8, tzinfo=timezone.utc),
        supply_lines=[
            {"source_ref": "NETWORK", "quantity": 53, "status": "confirmed",
             "arrival_max": "2026-08-11T06:00:00Z"},
            {"source_ref": "SUP", "quantity": 27, "status": "unconfirmed"},
        ],
        dependency_versions={"atp": "atp-7"},
    )

    verdict = critique_promise(
        proposal={"action": "promise_full", "payment_action": "capture_full"},
        feasibility=feasibility,
        calendar_expectation={"calendar_state": "closed", "freshness": "current"},
    )

    assert verdict["decision"] == "block"
    assert "full_promise_not_supported" in verdict["reason_codes"]
    assert "full_capture_against_unconfirmed_supply" in verdict["reason_codes"]
    assert verdict["external_action"] == "none"


def test_critic_requires_buyer_consent_for_mixed_product_recovery() -> None:
    verdict = critique_promise(
        proposal={"action": "offer_substitute", "substitute_selected": True,
                  "buyer_substitute_consent": False},
        feasibility={"feasibility": "met", "unknown_quantity": 0, "reason_codes": []},
        calendar_expectation={"calendar_state": "open", "freshness": "current"},
    )

    assert verdict["decision"] == "block"
    assert verdict["state_prevented"] == "unconsented_substitution"


def test_execution_gate_blocks_unknown_full_delivery_promise(monkeypatch) -> None:
    from src.app.policy import execution_gate
    from src.app.policy.action_authority_matrix import AuthDecision

    monkeypatch.setattr(execution_gate, "record_policy_decision", lambda *args, **kwargs: None)
    verdict = execution_gate.decide(
        "order_accept", tenant_id="tenant-a", actor="buyer-agent",
        context={
            "promise_feasibility": {
                "feasibility": "unknown", "unknown_quantity": 27,
                "reason_codes": ["supply_confirmation_required"],
                "dependency_versions": {"atp": "snapshot-8"},
            },
            "calendar_state": "closed", "calendar_freshness": "current",
        },
    )
    assert verdict.decision == AuthDecision.BLOCK
    assert verdict.rule_id == "PROMISE-TEMPORAL-01"
    assert verdict.context["temporal_promise_critic"]["state_prevented"] == "unsupported_commercial_promise"


def test_critical_path_marks_missed_carrier_cutoff_and_preserves_dependencies() -> None:
    result = evaluate_critical_path(
        requested_quantity=27, requested_arrival_at="2026-08-11T17:00:00+10:00",
        evaluated_at="2026-08-11T09:00:00+10:00",
        supply_lines=[{
            "source_ref": "SUP-1", "quantity": 27, "status": "confirmed",
            "arrival_max": "2026-08-11T17:00:00+10:00",
        }],
        dependency_versions={"calendar": "cal-3", "carrier_cutoff": "cutoff-13h-v1"},
        response_expectation={
            "calendar_state": "open", "freshness": "current",
            "quote_due_at": "2026-08-11T12:30:00+10:00",
        },
        stage_duration_seconds={
            "operator_authorization": (900, 1800),
            "allocation_confirmation": (300, 600),
            "dispatch_preparation": (900, 1800),
            "transit": (7200, 10800),
            "inspection_or_cross_dock": (0, 0),
            "final_mile": (1800, 3600),
        },
        carrier_cutoff_at="2026-08-11T13:00:00+10:00",
    )
    assert result["feasibility"] == "missed"
    assert "carrier_cutoff_missed" in result["failed_constraints"]
    assert result["latest_viable_supplier_response_at"] is not None
    assert result["dependency_versions"]["carrier_cutoff"] == "cutoff-13h-v1"


def test_critical_path_with_missing_stage_is_unknown() -> None:
    result = evaluate_critical_path(
        requested_quantity=1, requested_arrival_at="2026-08-12T17:00:00+10:00",
        evaluated_at="2026-08-11T09:00:00+10:00",
        supply_lines=[{
            "source_ref": "SUP-1", "quantity": 1, "status": "confirmed",
            "arrival_max": "2026-08-12T12:00:00+10:00",
        }],
        dependency_versions={"calendar": "cal-3"},
        response_expectation={
            "calendar_state": "open", "freshness": "current",
            "quote_due_at": "2026-08-11T11:00:00+10:00",
        },
        stage_duration_seconds={},
    )
    assert result["feasibility"] == "unknown"
    assert "critical_path_stage_missing" in result["failed_constraints"]
