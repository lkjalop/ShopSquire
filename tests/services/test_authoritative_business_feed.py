from __future__ import annotations

import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text

from src.app.models.db import set_engine
from src.app.services.authoritative_business_feed import (
    BusinessObservation,
    SUPPORTED_ENTITY_TYPES,
    ingest_authoritative_observations,
)


def _apply_migration(engine) -> None:
    for filename in (
        "20260809_authoritative_business_feed.py",
        "20260813_canonical_business_semantics.py",
    ):
        path = Path(__file__).resolve().parents[2] / "alembic" / "versions" / filename
        spec = importlib.util.spec_from_file_location(filename.replace(".", "_"), path)
        module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(module)
        with engine.begin() as connection:
            operations = Operations(MigrationContext.configure(connection))
            original = module.op
            module.op = operations
            try:
                module.upgrade()
            finally:
                module.op = original


def _payload(entity: str, index: int) -> dict:
    quantity = {"value": 2, "uom": "EA"}
    money = {"amount_minor": index * 100, "currency": "AUD"}
    return {
        "order": {"party_external_id": "buyer-1", "status": "paid", "total": money},
        "order_line": {
            "order_external_id": "order-1", "variant_id": "variant-1",
            "quantity": quantity, "unit_price": money,
        },
        "location_atp": {
            "variant_id": "variant-1", "location_id": "loc-1",
            "on_hand": quantity, "committed": {"value": 1, "uom": "EA"},
            "source_calculated_at": "2026-07-28T00:00:00Z",
        },
        "reservation": {
            "variant_id": "variant-1", "location_id": "loc-1",
            "quantity": quantity, "status": "held", "idempotency_key": "hold-1",
        },
        "return": {
            "order_external_id": "order-1", "variant_id": "variant-1",
            "quantity": quantity, "physical_disposition": "restock",
            "financial_disposition": "credited",
        },
        "receipt": {
            "purchase_order_external_id": "po-1", "variant_id": "variant-1",
            "location_id": "loc-1", "quantity": quantity,
            "custody_status": "accepted", "ownership_status": "owned", "unit_cost": money,
        },
        "invoice": {"party_external_id": "supplier-1", "status": "posted", "total": money},
        "invoice_line": {
            "invoice_external_id": "invoice-1",
            "purchase_order_external_id": "po-1",
            "receipt_external_ids": ["receipt-1"],
            "variant_id": "variant-1",
            "quantity": quantity,
            "unit_cost": money,
        },
        "purchase_order": {"supplier_external_id": "supplier-1", "status": "open", "total": money},
        "inventory_valuation": {
            "variant_id": "variant-1", "location_id": "loc-1",
            "quantity": quantity, "value": money, "costing_method": "fifo",
            "layer_ref": f"layer-{index}",
        },
        "landed_cost": {
            "applies_to": ["receipt-1"], "cost": money, "allocation_method": "quantity",
        },
        "transfer": {
            "variant_id": "variant-1", "from_location_id": "loc-1",
            "to_location_id": "loc-2", "quantity": quantity, "status": "in_transit",
        },
        "inspection": {
            "receipt_external_id": "receipt-1", "variant_id": "variant-1",
            "quantity": quantity, "outcome": "accepted",
        },
        "inventory_adjustment": {
            "variant_id": "variant-1", "location_id": "loc-1",
            "quantity_delta": -1, "uom": "EA", "reason_code": "cycle_count",
            "approved_by": "operator-1",
        },
        "markdown": {
            "variant_id": "variant-1",
            "location_id": "loc-1",
            "original_price": {"amount_minor": 200, "currency": "AUD"},
            "new_price": {"amount_minor": 150, "currency": "AUD"},
            "reason_code": "stale_stock",
            "effective_at": "2026-07-28T00:00:00Z",
            "approved_by": "operator-1",
        },
        "disposal": {
            "variant_id": "variant-1",
            "location_id": "loc-1",
            "quantity": quantity,
            "reason_code": "expired",
            "writeoff": money,
            "approved_by": "operator-1",
        },
        "procurement_reconciliation": {
            "purchase_order_external_id": "po-1",
            "invoice_external_id": "invoice-1",
            "receipt_external_ids": ["receipt-1"],
            "variant_id": "variant-1",
            "ordered_quantity": quantity,
            "received_quantity": quantity,
            "invoiced_quantity": quantity,
            "quantity_tolerance": 0,
            "ordered_unit_cost": money,
            "invoiced_unit_cost": money,
            "status": "matched",
            "exception_reasons": [],
        },
    }[entity]


def test_all_authoritative_entities_are_append_only_and_tenant_scoped(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'facts.sqlite'}", future=True)
    _apply_migration(engine)
    set_engine(engine)
    observations = [
        BusinessObservation(
            entity_type=entity,
            external_id=f"shared-{index}",
            event_time="2026-07-28T00:00:00Z",
            payload=_payload(entity, index),
        )
        for index, entity in enumerate(sorted(SUPPORTED_ENTITY_TYPES), start=1)
    ]
    first = ingest_authoritative_observations(
        tenant_id="tenant-a", source="design-partner-csv", observations=observations
    )
    replay = ingest_authoritative_observations(
        tenant_id="tenant-a", source="design-partner-csv", observations=observations
    )
    other_tenant = ingest_authoritative_observations(
        tenant_id="tenant-b", source="design-partner-csv", observations=observations
    )
    assert first["status"] == "observed"
    assert first["records_inserted"] == len(SUPPORTED_ENTITY_TYPES)
    assert replay["records_inserted"] == 0
    assert replay["records_replayed"] == len(SUPPORTED_ENTITY_TYPES)
    assert other_tenant["records_inserted"] == len(SUPPORTED_ENTITY_TYPES)
    with engine.connect() as connection:
        counts = dict(
            connection.execute(
                text(
                    """
                    SELECT tenant_id, COUNT(*)
                    FROM authoritative_business_observation
                    GROUP BY tenant_id
                    """
                )
            ).fetchall()
        )
    assert counts == {
        "tenant-a": len(SUPPORTED_ENTITY_TYPES),
        "tenant-b": len(SUPPORTED_ENTITY_TYPES),
    }


def test_correction_references_prior_observation_without_mutating_payload(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'correction.sqlite'}", future=True)
    _apply_migration(engine)
    set_engine(engine)
    original = BusinessObservation(
        entity_type="inventory_adjustment",
        external_id="adjustment-1",
        event_time="2026-07-28T00:00:00Z",
        payload=_payload("inventory_adjustment", 1),
    )
    assert ingest_authoritative_observations(
        tenant_id="tenant-a", source="wms", observations=[original]
    )["records_inserted"] == 1
    with engine.connect() as connection:
        prior_id, prior_payload = connection.execute(
            text(
                "SELECT id,payload_json FROM authoritative_business_observation "
                "WHERE tenant_id='tenant-a'"
            )
        ).one()
    correction = BusinessObservation(
        entity_type="inventory_adjustment",
        external_id="adjustment-1-correction",
        event_time="2026-07-28T01:00:00Z",
        payload=_payload("inventory_adjustment", 1) | {"quantity_delta": -2},
        corrects_observation_id=prior_id,
    )
    assert ingest_authoritative_observations(
        tenant_id="tenant-a", source="wms", observations=[correction]
    )["records_inserted"] == 1
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT payload_json,event_kind,corrects_observation_id "
                "FROM authoritative_business_observation ORDER BY event_time"
            )
        ).fetchall()
    assert len(rows) == 2
    assert rows[0][0] == prior_payload
    assert rows[0][1] == "observation"
    assert rows[1][1:] == ("correction", prior_id)
