from __future__ import annotations

from src.app.services.authoritative_business_feed import business_observation_id
from src.app.services.business_semantics import validate_payload
from src.app.services.synthetic_canonical_replay import materialize_canonical_replay
from src.app.services.synthetic_replay_acceptance import build_acceptance_report
from src.app.services.synthetic_replay_shadow import evaluate_shadow_decisions


def test_extended_canonical_contracts_are_typed_and_comparable():
    markdown = validate_payload("markdown", {
        "variant_id": "variant:a",
        "location_id": "location:a",
        "original_price": {"amount_minor": 1500, "currency": "USD"},
        "new_price": {"amount_minor": 1200, "currency": "USD"},
        "reason_code": "stale_stock",
        "effective_at": "2026-01-01T00:00:00Z",
        "approved_by": "synthetic-policy",
    })
    assert markdown["kind"] == "markdown"

    reconciliation = validate_payload("procurement_reconciliation", {
        "purchase_order_external_id": "po-1",
        "invoice_external_id": "invoice-1",
        "receipt_external_ids": ["receipt-1"],
        "variant_id": "variant:a",
        "ordered_quantity": {"value": 10, "uom": "EA"},
        "received_quantity": {"value": 9, "uom": "EA"},
        "invoiced_quantity": {"value": 10, "uom": "EA"},
        "quantity_tolerance": 1,
        "ordered_unit_cost": {"amount_minor": 100, "currency": "USD"},
        "invoiced_unit_cost": {"amount_minor": 102, "currency": "USD"},
        "status": "within_tolerance",
    })
    assert reconciliation["kind"] == "procurement_reconciliation"


def test_replay_materializes_append_only_canonical_event_families():
    replay = materialize_canonical_replay(
        "perishable_cold_chain",
        seed=23,
        days=400,
        tenant_id="synthetic-lab",
    )
    observations = replay["observations"]
    entity_types = {item.entity_type for item in observations}
    assert {
        "order",
        "order_line",
        "location_atp",
        "purchase_order",
        "receipt",
        "transfer",
        "inspection",
        "return",
        "markdown",
        "disposal",
        "invoice",
        "invoice_line",
        "procurement_reconciliation",
        "inventory_adjustment",
    } <= entity_types
    assert replay["manifest"]["authority"] == "simulation_only"
    assert all(
        observations[index].event_time <= observations[index + 1].event_time
        for index in range(len(observations) - 1)
    )

    corrections = [row for row in observations if row.corrects_observation_id]
    reversals = [row for row in observations if row.reverses_observation_id]
    assert corrections and reversals
    known_ids = {
        business_observation_id(
            tenant_id="synthetic-lab",
            source=replay["manifest"]["source"],
            observation=row,
        )
        for row in observations
    }
    assert all(row.corrects_observation_id in known_ids for row in corrections)
    assert all(row.reverses_observation_id in known_ids for row in reversals)


def test_acceptance_report_exposes_structural_statistical_and_utility_gates():
    replay = materialize_canonical_replay(
        "intermittent_critical_spare",
        seed=91,
        days=400,
        tenant_id="synthetic-lab",
    )
    report = build_acceptance_report(replay)
    assert report["authority"] == "simulation_only"
    assert report["structural_fidelity"]["inventory_conservation"]["status"] == "passed"
    assert report["structural_fidelity"]["event_ordering"]["status"] == "passed"
    assert report["statistical_fidelity"]["zero_demand_rate"]["value"] > 0.5
    assert report["causal_interventions"]["status"] == "passed"
    assert report["forecast_discrimination"]["status"] in {
        "passed", "observed", "undefined",
    }
    assert report["prediction_interval_coverage"]["status"] in {
        "observed", "undefined",
    }
    assert report["business_utility"]["fill_rate"] is not None
    assert report["overall_status"] in {"passed", "passed_with_warnings"}


def test_shadow_decisions_never_gain_execution_authority():
    replay = materialize_canonical_replay(
        "bulky_freight_exposure",
        seed=17,
        days=400,
        tenant_id="synthetic-lab",
    )
    result = evaluate_shadow_decisions(replay)
    assert result["authority"] == "shadow_only"
    assert result["execution_allowed"] is False
    assert result["replenishment"]["execution_allowed"] is False
    assert result["supplier_score"]["execution_allowed"] is False
    assert result["inventory"]["stale_price_proposal"] is None or (
        result["inventory"]["stale_price_proposal"]["execution_allowed"] is False
    )
