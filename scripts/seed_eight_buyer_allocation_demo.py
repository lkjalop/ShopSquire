"""Seed a deterministic, simulation-only eight-buyer allocation scenario."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from src.app.models.db import db_session
from src.app.services.demand_allocation import (
    allocate_committed,
    apply_supplier_schedule_to_batch,
    consolidate_shortfalls,
    create_sourcing_wave,
    materialize_governed_rfq_for_wave,
    record_demand,
    upsert_supply_snapshot,
)


TENANT = "default"
BASE_SKU = "RGAM-0007"
SKU = "SIM-RGAM-0007"
LOCATION = "sydney"
SCENARIO = "simulation:eight-buyer-v2"


def seed() -> dict:
    now = datetime.now(timezone.utc)
    expires = (now + timedelta(hours=4)).isoformat()
    with db_session() as db:
        supplier = db.execute(text(
            "SELECT s.id FROM suppliers s JOIN supplier_products p ON p.supplier_id=s.id "
            "JOIN trusted_supplier_domains d ON d.supplier_id=s.id AND d.active=1 "
            "WHERE p.sku=:sku AND s.active=1 ORDER BY s.reliability_score DESC,s.id LIMIT 1"
        ), {"sku": BASE_SKU}).fetchone()
        if supplier is None:
            raise RuntimeError("eight_buyer_demo_requires_approved_supplier")
        supplier_id = str(supplier[0])
        product_link = db.execute(text(
            "SELECT 1 FROM supplier_products WHERE supplier_id=:supplier AND sku=:sku LIMIT 1"
        ), {"supplier": supplier_id, "sku": SKU}).fetchone()
        if product_link is None:
            db.execute(text(
                "INSERT INTO supplier_products (id,supplier_id,sku) VALUES (:id,:supplier,:sku)"
            ), {"id": str(uuid.uuid4()), "supplier": supplier_id, "sku": SKU})
        upsert_supply_snapshot(
            db, tenant_id=TENANT, sku=SKU, uom="each", location_id=LOCATION,
            atp_quantity=53, snapshot_version="eight-buyer-atp-v1",
            observed_at=now.isoformat(), expires_at=expires, source_id=SCENARIO,
            source_authority="authoritative", completeness="source_supplied",
            source_observation_id="simulation-eight-buyer-atp-v1",
        )
        demands = []
        for index in range(1, 9):
            demands.append(record_demand(
                db, tenant_id=TENANT, idempotency_key=f"{SCENARIO}:buyer-{index}",
                case_id=f"SIM-ORDER-{index}", buyer_ref_hash=f"sim-buyer-{index:02d}",
                sku=SKU, uom="each", quantity=10, destination_id="merchant:SYD",
                fulfillment_location_id=LOCATION, stage="committed", priority_tier=50,
                required_by="2026-09-18",
            ))
        allocation = allocate_committed(
            db, tenant_id=TENANT, sku=SKU, uom="each", location_id=LOCATION,
        )
        batches = consolidate_shortfalls(
            db, tenant_id=TENANT, supplier_id=supplier_id,
            window_ends_at=(now + timedelta(minutes=30)).isoformat(),
            # The scenario must remain reproducible even when run in a test database that contains
            # unrelated historical draft batches. Production callers keep the governed default.
            max_open_batches=10_000,
        )
        batch = next((row for row in batches if row.get("sku") == SKU), None)
        if batch is None:
            raise RuntimeError(
                f"eight_buyer_demo_batch_not_created: allocation={allocation!r}; batches={batches!r}"
            )
        wave = create_sourcing_wave(
            db, tenant_id=TENANT, supplier_id=supplier_id,
            supplier_facility_id=f"{supplier_id}:primary-dc", currency="AUD", incoterm="DAP",
            merchant_destination_id="merchant:SYD", window_ends_at=(now + timedelta(minutes=30)).isoformat(),
            batch_ids=[batch["id"]], standalone_freight_cents=18_000,
            consolidated_freight_cents=12_000, handling_cents=2_000,
        )
        db.commit()
    with db_session() as db:
        recovery = apply_supplier_schedule_to_batch(
            db, tenant_id=TENANT, batch_id=batch["id"], supplier_id=supplier_id,
            evidence_id="simulation-supplier-partial-v1",
            schedule_lines=[
                {"status": "partial", "quantity": 18, "eta": "2026-08-09"},
                {"status": "rejected", "quantity": 9},
            ], observed_at=now.isoformat(), expires_at=expires,
        )
        db.commit()
    with db_session() as db:
        rfq = materialize_governed_rfq_for_wave(
            db, tenant_id=TENANT, wave_id=wave["wave_id"], trace_id="SIM-EIGHT-BUYER-TRACE",
        )
        db.commit()
    return {
        "scenario": SCENARIO, "simulation_only": True, "sku": SKU,
        "buyer_count": len(demands), "requested": 80, "atp": 53,
        "allocated": sum(int(row["quantity"]) for row in allocation["allocated"]),
        "shortfall": 27,
        "supplier_confirmed": recovery["confirmed_quantity"],
        "supplier_unresolved": recovery["unresolved_quantity"],
        "wave_id": wave["wave_id"], "batch_id": batch["id"], "rfq": rfq,
    }


def main() -> int:
    print(json.dumps(seed(), indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
