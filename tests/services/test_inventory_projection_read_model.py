from __future__ import annotations

import importlib.util
from decimal import Decimal
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text

from src.app.models.db import set_engine
from src.app.services.authoritative_business_feed import (
    BusinessObservation,
    business_observation_id,
    ingest_authoritative_observations,
)
from src.app.services.inventory_event_projection import project_inventory_events
from src.app.services.inventory_projection_read_model import (
    inventory_projection_status,
    inventory_projection_rows,
    rebuild_inventory_projection,
)
from src.app.services.product_identity import (
    governed_convert_uom,
    register_uom,
    register_uom_conversion,
)


def _migrate(engine) -> None:
    root = Path(__file__).resolve().parents[2] / "alembic" / "versions"
    for filename in (
        "20260809_authoritative_business_feed.py",
        "20260813_canonical_business_semantics.py",
        "20260820_inventory_projection.py",
    ):
        path = root / filename
        spec = importlib.util.spec_from_file_location(filename, path)
        module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(module)
        with engine.begin() as connection:
            original = module.op
            module.op = Operations(MigrationContext.configure(connection))
            try:
                module.upgrade()
            finally:
                module.op = original


def _event(
    entity_type: str,
    external_id: str,
    event_time: str,
    payload: dict,
    *,
    corrects: str | None = None,
    reverses: str | None = None,
) -> BusinessObservation:
    return BusinessObservation(
        entity_type=entity_type,
        external_id=external_id,
        event_time=event_time,
        payload=payload,
        corrects_observation_id=corrects,
        reverses_observation_id=reverses,
    )


def test_rebuild_is_deterministic_idempotent_and_preserves_custody(tmp_path):
    engine = create_engine(
        f"sqlite+pysqlite:///{tmp_path / 'projection.sqlite'}",
        future=True,
    )
    _migrate(engine)
    set_engine(engine)
    events = [
        _event("receipt", "r1", "2026-01-01T00:00:00Z", {
            "purchase_order_external_id": "po1",
            "variant_id": "v1",
            "location_id": "a",
            "quantity": {"value": 10, "uom": "EA"},
            "custody_status": "arrived",
            "ownership_status": "owned",
        }),
        _event("inspection", "i1", "2026-01-01T01:00:00Z", {
            "receipt_external_id": "r1",
            "variant_id": "v1",
            "location_id": "a",
            "quantity": {"value": 10, "uom": "EA"},
            "outcome": "accepted",
        }),
        _event("transfer", "t1", "2026-01-01T02:00:00Z", {
            "variant_id": "v1",
            "from_location_id": "a",
            "to_location_id": "b",
            "quantity": {"value": 3, "uom": "EA"},
            "status": "received",
        }),
        _event("return", "return1", "2026-01-01T03:00:00Z", {
            "order_external_id": "o1",
            "variant_id": "v1",
            "location_id": "b",
            "quantity": {"value": 1, "uom": "EA"},
            "physical_disposition": "quarantine",
            "financial_disposition": "refunded",
        }),
        _event("disposal", "d1", "2026-01-01T04:00:00Z", {
            "variant_id": "v1",
            "location_id": "b",
            "quantity": {"value": 1, "uom": "EA"},
            "custody_from": "quarantined",
            "reason_code": "damage",
            "approved_by": "operator-1",
        }),
    ]
    assert ingest_authoritative_observations(
        tenant_id="tenant-a", source="wms", observations=events
    )["status"] == "observed"

    first = rebuild_inventory_projection(tenant_id="tenant-a", source="wms")
    first_rows = inventory_projection_rows(tenant_id="tenant-a", source="wms")
    second = rebuild_inventory_projection(tenant_id="tenant-a", source="wms")

    assert first["status"] == "ready"
    assert second["run_id"] == first["run_id"]
    assert second["projection_hash"] == first["projection_hash"]
    assert inventory_projection_rows(tenant_id="tenant-a", source="wms") == first_rows
    assert [
        (row["location_id"], row["custody"], row["quantity"])
        for row in first_rows
    ] == [("a", "available", "7"), ("b", "available", "3")]
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT COUNT(*) FROM inventory_projection_run")
        ).scalar_one() == 1


def test_empty_authoritative_history_is_insufficient_not_execution_ready(tmp_path):
    engine = create_engine(
        f"sqlite+pysqlite:///{tmp_path / 'empty-projection.sqlite'}",
        future=True,
    )
    _migrate(engine)
    set_engine(engine)

    result = rebuild_inventory_projection(tenant_id="tenant-a", source="wms")

    assert result["status"] == "insufficient"
    assert result["execution_allowed"] is False
    status = inventory_projection_status(tenant_id="tenant-a", source="wms")
    assert status["runs"][0]["status"] == "insufficient"
    assert status["execution_policy"]["hidden_compensation_allowed"] is False
    assert status["exceptions"][0]["exception_type"] == "insufficient_data"
    with engine.connect() as connection:
        assert connection.execute(
            text(
                "SELECT exception_type FROM inventory_projection_exception "
                "WHERE tenant_id='tenant-a'"
            )
        ).scalar_one() == "insufficient_data"


def test_correction_reversal_and_negative_atp_mismatch_are_quarantined(tmp_path):
    engine = create_engine(
        f"sqlite+pysqlite:///{tmp_path / 'quarantine.sqlite'}",
        future=True,
    )
    _migrate(engine)
    set_engine(engine)
    original = _event("inventory_adjustment", "count", "2026-01-01T00:00:00Z", {
        "variant_id": "v1", "location_id": "a", "quantity_delta": 5,
        "uom": "EA", "reason_code": "opening",
    })
    original_id = business_observation_id(
        tenant_id="tenant-a", source="wms", observation=original
    )
    correction = _event(
        "inventory_adjustment", "count-c", "2026-01-01T01:00:00Z",
        {
            "variant_id": "v1", "location_id": "a", "quantity_delta": 2,
            "uom": "EA", "reason_code": "correction",
        },
        corrects=original_id,
    )
    correction_id = business_observation_id(
        tenant_id="tenant-a", source="wms", observation=correction
    )
    reversal = _event(
        "inventory_adjustment", "count-r", "2026-01-01T02:00:00Z",
        {
            "variant_id": "v1", "location_id": "a", "quantity_delta": 2,
            "uom": "EA", "reason_code": "reversal",
        },
        reverses=correction_id,
    )
    sale = _event("order_line", "sale", "2026-01-01T03:00:00Z", {
        "order_external_id": "o1", "variant_id": "v1", "location_id": "a",
        "quantity": {"value": 7, "uom": "EA"},
        "unit_price": {"amount_minor": 100, "currency": "AUD"},
    })
    atp = _event("location_atp", "atp", "2026-01-01T04:00:00Z", {
        "variant_id": "v1", "location_id": "a",
        "source_atp": {"value": 1, "uom": "EA"},
        "source_calculated_at": "2026-01-01T04:00:00Z",
    })
    ingest_authoritative_observations(
        tenant_id="tenant-a",
        source="wms",
        observations=[original, correction, reversal, sale, atp],
    )

    result = rebuild_inventory_projection(tenant_id="tenant-a", source="wms")

    assert result["status"] == "quarantined"
    assert result["execution_allowed"] is False
    assert inventory_projection_rows(
        tenant_id="tenant-a", source="wms"
    )[0]["quantity"] == "-2"
    with engine.connect() as connection:
        kinds = {
            row[0]
            for row in connection.execute(
                text("SELECT exception_type FROM inventory_projection_exception")
            )
        }
    assert kinds == {"atp_reconciliation", "negative_balance"}


def test_governed_effective_conversion_pack_rounding_and_incomparability(tmp_path):
    engine = create_engine(
        f"sqlite+pysqlite:///{tmp_path / 'uom.sqlite'}",
        future=True,
    )
    _migrate(engine)
    set_engine(engine)
    register_uom(
        tenant_id="tenant-a", category="count", code="EA",
        factor_to_base=Decimal(1), is_base=True,
    )
    register_uom(
        tenant_id="tenant-a", category="count", code="PACK",
        factor_to_base=Decimal(6),
    )
    register_uom(
        tenant_id="tenant-a", category="weight", code="KG",
        factor_to_base=Decimal(1), is_base=True,
    )
    authority_id = register_uom_conversion(
        tenant_id="tenant-a",
        from_code="PACK",
        to_code="EA",
        factor=Decimal(6),
        effective_from="2026-01-01T00:00:00Z",
        source="supplier-contract",
        source_record_id="terms-v2",
        approved_by="buyer-1",
        rounding_mode="exact",
    )

    before = governed_convert_uom(
        tenant_id="tenant-a", value=Decimal(2),
        from_code="PACK", to_code="EA",
        at_time="2025-12-31T23:59:59Z",
    )
    after = governed_convert_uom(
        tenant_id="tenant-a", value=Decimal(2),
        from_code="PACK", to_code="EA",
        at_time="2026-01-01T00:00:00Z",
    )
    wrong_category = governed_convert_uom(
        tenant_id="tenant-a", value=Decimal(2),
        from_code="PACK", to_code="KG",
        at_time="2026-02-01T00:00:00Z",
    )
    assert before.status == "incomparable"
    assert before.reason == "approved_effective_conversion_unavailable"
    assert after.value == Decimal(12)
    assert after.authority_id == authority_id
    assert wrong_category.status == "incomparable"
    assert wrong_category.reason == "uom_category_mismatch"


def test_atp_with_multiple_projected_uoms_is_explicitly_incomparable():
    events = [
        _event("inventory_adjustment", "ea", "2026-01-01T00:00:00Z", {
            "variant_id": "v1", "location_id": "a",
            "quantity_delta": 1, "uom": "EA", "reason_code": "opening",
        }),
        _event("inventory_adjustment", "pack", "2026-01-01T01:00:00Z", {
            "variant_id": "v1", "location_id": "a",
            "quantity_delta": 1, "uom": "PACK", "reason_code": "opening",
        }),
        _event("location_atp", "atp", "2026-01-01T02:00:00Z", {
            "variant_id": "v1", "location_id": "a",
            "source_atp": {"value": 7, "uom": "EA"},
            "source_calculated_at": "2026-01-01T02:00:00Z",
        }),
    ]

    result = project_inventory_events(
        events, tenant_id="tenant-a", source="wms"
    )
    checkpoint = result["atp_reconciliation"]["checkpoints"][0]
    assert checkpoint["status"] == "not_comparable"
    assert checkpoint["reason"] == "multiple_projected_uoms"
    assert checkpoint["projected_available"] is None


def test_transfer_status_progression_and_quarantine_release_are_not_double_counted():
    events = [
        _event("inventory_adjustment", "opening", "2026-01-01T00:00:00Z", {
            "variant_id": "v1", "location_id": "a",
            "quantity_delta": 10, "uom": "EA", "reason_code": "opening",
        }),
        _event("transfer", "transfer-1", "2026-01-01T01:00:00Z", {
            "variant_id": "v1", "from_location_id": "a", "to_location_id": "b",
            "quantity": {"value": 2, "uom": "EA"}, "status": "in_transit",
        }),
        _event("transfer", "transfer-1", "2026-01-01T02:00:00Z", {
            "variant_id": "v1", "from_location_id": "a", "to_location_id": "b",
            "quantity": {"value": 2, "uom": "EA"}, "status": "received",
        }),
        _event("receipt", "receipt-1", "2026-01-01T03:00:00Z", {
            "purchase_order_external_id": "po1", "variant_id": "v1",
            "location_id": "b", "quantity": {"value": 3, "uom": "EA"},
            "custody_status": "arrived", "ownership_status": "owned",
        }),
        _event("inspection", "inspect-q", "2026-01-01T04:00:00Z", {
            "receipt_external_id": "receipt-1", "variant_id": "v1",
            "location_id": "b", "quantity": {"value": 3, "uom": "EA"},
            "outcome": "quarantined",
        }),
        _event("inspection", "inspect-release", "2026-01-01T05:00:00Z", {
            "receipt_external_id": "receipt-1", "variant_id": "v1",
            "location_id": "b", "quantity": {"value": 3, "uom": "EA"},
            "outcome": "accepted",
        }),
    ]

    result = project_inventory_events(
        events, tenant_id="tenant-a", source="wms"
    )
    balances = {
        (row["location_id"], row["custody"]): row["quantity"]
        for row in result["balances"]
    }
    assert balances == {("a", "available"): 8, ("b", "available"): 5}
    assert result["balance_integrity"]["status"] == "passed"
    assert result["conservation"]["status"] == "passed"
