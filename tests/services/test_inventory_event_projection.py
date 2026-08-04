from __future__ import annotations

import copy

from src.app.services.authoritative_business_feed import (
    BusinessObservation,
    business_observation_id,
)
from src.app.services.inventory_event_projection import project_inventory_events
from src.app.services.synthetic_canonical_replay import materialize_canonical_replay


TENANT = "tenant-a"
SOURCE = "synthetic-test"


def _event(
    entity_type: str,
    external_id: str,
    hour: int,
    payload: dict,
    *,
    corrects: str | None = None,
    reverses: str | None = None,
) -> BusinessObservation:
    return BusinessObservation(
        entity_type=entity_type,
        external_id=external_id,
        event_time=f"2026-01-01T{hour:02d}:00:00Z",
        payload=payload,
        corrects_observation_id=corrects,
        reverses_observation_id=reverses,
    )


def _qty(value: int) -> dict:
    return {"value": value, "uom": "EA"}


def test_projects_complete_custody_journey_and_reconciles_atp_without_mutation():
    events = [
        _event("inventory_adjustment", "opening", 0, {
            "variant_id": "sku-1", "location_id": "a",
            "quantity_delta": 10, "uom": "EA", "reason_code": "opening",
        }),
        _event("receipt", "receipt-1", 1, {
            "purchase_order_external_id": "po-1", "variant_id": "sku-1",
            "location_id": "a", "quantity": _qty(6),
            "custody_status": "arrived", "ownership_status": "owned",
        }),
        _event("inspection", "inspection-1", 2, {
            "receipt_external_id": "receipt-1", "variant_id": "sku-1",
            "location_id": "a", "quantity": _qty(6),
            "outcome": "quarantined", "reason_code": "check",
        }),
        _event("transfer", "transfer-1", 3, {
            "variant_id": "sku-1", "from_location_id": "a",
            "to_location_id": "b", "quantity": _qty(2), "status": "received",
        }),
        _event("return", "return-1", 4, {
            "order_external_id": "order-1", "variant_id": "sku-1",
            "location_id": "b", "quantity": _qty(1),
            "physical_disposition": "repair", "financial_disposition": "refunded",
        }),
        _event("disposal", "disposal-1", 5, {
            "variant_id": "sku-1", "location_id": "a", "quantity": _qty(1),
            "custody_from": "quarantined", "reason_code": "failed_inspection",
            "approved_by": "operator",
        }),
        _event("location_atp", "atp-a", 9, {
            "variant_id": "sku-1", "location_id": "a",
            "source_atp": _qty(8), "source_basis": ["canonical_event_projection_v1"],
            "source_calculated_at": "2026-01-01T09:00:00Z",
        }),
        _event("location_atp", "atp-b", 9, {
            "variant_id": "sku-1", "location_id": "b",
            "source_atp": _qty(2), "source_basis": ["canonical_event_projection_v1"],
            "source_calculated_at": "2026-01-01T09:00:00Z",
        }),
    ]
    original = copy.deepcopy(events)

    result = project_inventory_events(
        events, tenant_id=TENANT, source=SOURCE, default_location_id="a"
    )

    balances = {
        (row["location_id"], row["custody"]): row["quantity"]
        for row in result["balances"]
    }
    assert balances == {
        ("a", "available"): 8,
        ("a", "quarantined"): 5,
        ("b", "available"): 2,
        ("b", "repair"): 1,
    }
    assert result["conservation"]["status"] == "passed"
    assert result["atp_reconciliation"]["status"] == "matched"
    assert events == original


def test_correction_replaces_adjustment_and_reversal_restores_original():
    original = _event("inventory_adjustment", "count-1", 1, {
        "variant_id": "sku-1", "location_id": "a",
        "quantity_delta": 5, "uom": "EA", "reason_code": "count",
    })
    original_id = business_observation_id(
        tenant_id=TENANT, source=SOURCE, observation=original
    )
    correction = _event("inventory_adjustment", "count-1-correction", 2, {
        "variant_id": "sku-1", "location_id": "a",
        "quantity_delta": 7, "uom": "EA", "reason_code": "corrected_count",
    }, corrects=original_id)
    correction_id = business_observation_id(
        tenant_id=TENANT, source=SOURCE, observation=correction
    )
    reversal = _event("inventory_adjustment", "count-1-reversal", 3, {
        "variant_id": "sku-1", "location_id": "a",
        "quantity_delta": 7, "uom": "EA", "reason_code": "corrected_count",
    }, reverses=correction_id)
    atp = _event("location_atp", "atp", 4, {
        "variant_id": "sku-1", "location_id": "a",
        "source_atp": _qty(5), "source_basis": ["canonical_event_projection_v1"],
        "source_calculated_at": "2026-01-01T04:00:00Z",
    })

    result = project_inventory_events(
        [original, correction, reversal, atp],
        tenant_id=TENANT,
        source=SOURCE,
        default_location_id="a",
    )

    assert result["balances"][0]["quantity"] == 5
    assert [row["physical_delta"] for row in result["events"]] == [5, 2, -2]
    assert result["atp_reconciliation"]["status"] == "matched"


def test_atp_is_a_non_mutating_checkpoint_and_reports_mismatch():
    events = [
        _event("inventory_adjustment", "opening", 0, {
            "variant_id": "sku-1", "location_id": "a",
            "quantity_delta": 3, "uom": "EA", "reason_code": "opening",
        }),
        _event("location_atp", "atp", 1, {
            "variant_id": "sku-1", "location_id": "a",
            "source_atp": _qty(4), "source_basis": ["source_wms"],
            "source_calculated_at": "2026-01-01T01:00:00Z",
        }),
    ]
    result = project_inventory_events(
        events, tenant_id=TENANT, source=SOURCE, default_location_id="a"
    )

    assert result["balances"][0]["quantity"] == 3
    assert result["atp_reconciliation"]["status"] == "mismatch"
    assert result["atp_reconciliation"]["mismatches"][0]["difference"] == 1


def test_atp_components_are_normalized_for_reconciliation():
    events = [
        _event("inventory_adjustment", "opening", 0, {
            "variant_id": "sku-1", "location_id": "a",
            "quantity_delta": 8, "uom": "EA", "reason_code": "opening",
        }),
        _event("location_atp", "atp", 1, {
            "variant_id": "sku-1", "location_id": "a",
            "on_hand": _qty(10), "committed": _qty(3),
            "incoming": _qty(2), "safety_stock": _qty(1),
            "source_basis": ["wms_components"],
            "source_calculated_at": "2026-01-01T01:00:00Z",
        }),
    ]

    checkpoint = project_inventory_events(
        events, tenant_id=TENANT, source=SOURCE, default_location_id="a"
    )["atp_reconciliation"]["checkpoints"][0]

    assert checkpoint["source_atp_basis"] == "normalized_source_components"
    assert checkpoint["source_atp"] == 8
    assert checkpoint["status"] == "matched"


def test_synthetic_replay_materializes_tenant_location_shadow_projection():
    replay = materialize_canonical_replay(
        "perishable_cold_chain",
        seed=23,
        days=400,
        tenant_id="tenant-projection-a",
    )
    projection = replay["inventory_projection"]

    assert replay["manifest"]["inventory_projection_authority"] == "shadow_only"
    assert projection["tenant_id"] == "tenant-projection-a"
    assert projection["conservation"]["status"] == "passed"
    assert {
        row["location_id"] for row in projection["balances"]
    } == {"location:primary", "location:secondary"}
    assert all(
        row["tenant_id"] == "tenant-projection-a"
        for row in projection["balances"]
    )
    # Source ATP is independent evidence. Differences are reported rather than
    # overwritten to make a generated fixture appear consistent.
    assert projection["atp_reconciliation"]["status"] == "mismatch"
    assert projection["atp_reconciliation"]["mismatches"]
    assert projection["balance_integrity"]["status"] == "failed"
    assert projection["balance_integrity"]["negative_balances"]

    other = materialize_canonical_replay(
        "perishable_cold_chain",
        seed=23,
        days=400,
        tenant_id="tenant-projection-b",
    )["inventory_projection"]
    assert other["tenant_id"] == "tenant-projection-b"
    assert all(
        row["tenant_id"] == "tenant-projection-b"
        for row in other["balances"]
    )
