"""Materialize buyer-commitment promise and payment consequences.

This projection is intentionally conservative.  A requested date or payment preference is
not proof that a carrier, supplier or payment policy can satisfy it.  The records make that
unknown/blocked state visible to operators and Decision Trace until authoritative evidence
supersedes them.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import inspect, text


def _tables(db) -> set[str]:
    return set(inspect(db.connection()).get_table_names())


def _order_total(db, lines: list[dict[str, Any]]) -> tuple[int, str]:
    total = 0
    currency = "AUD"
    for line in lines:
        sku = str(line.get("item_ref") or "").strip()
        quantity = max(0, int(line.get("quantity") or 0))
        if not sku or quantity == 0:
            continue
        row = db.execute(
            text("SELECT price_cents,COALESCE(currency,'AUD') FROM products WHERE sku=:sku LIMIT 1"),
            {"sku": sku},
        ).fetchone()
        if row and row[0] is not None:
            total += int(row[0]) * quantity
            currency = str(row[1] or currency)
    return total, currency


def project_commitment_consequences(
    db, *, tenant_id: str, case_id: str, calculated_at: str | None = None,
) -> dict[str, Any]:
    """Persist typed pre-supplier consequences, or return a typed unavailable result."""
    available = _tables(db)
    required = {"promise_calculation", "procurement_payment_consequence"}
    if not required <= available:
        return {"status": "schema_unavailable", "missing": sorted(required - available)}

    from src.app.services.fulfillment.repository import current_version

    current = current_version(db, case_id, tenant_id)
    if current is None or not isinstance(current.state_json, dict):
        return {"status": "case_not_found"}
    state = current.state_json
    requirements = state.get("requirements") if isinstance(state.get("requirements"), dict) else {}
    requested_arrival = str(
        requirements.get("required_by") or requirements.get("needed_by")
        or requirements.get("deadline") or ""
    ).strip()
    try:
        delivery_window_days = int(requirements.get("delivery_window_days") or 0)
    except (TypeError, ValueError):
        delivery_window_days = 0
    if not requested_arrival and delivery_window_days > 0:
        # A relative business-day request is preserved without inventing a UTC
        # deadline when the tenant calendar/holiday authority is absent.  The
        # resulting promise remains UNKNOWN and explicitly requests that evidence.
        requested_arrival = f"relative:{delivery_window_days}:business_days"
    payment_plan = str(requirements.get("payment_plan") or "").strip().lower()
    if not requested_arrival and not payment_plan:
        return {"status": "not_requested"}

    now = calculated_at or datetime.now(timezone.utc).isoformat()
    availability = state.get("availability") if isinstance(state.get("availability"), dict) else {}
    requested = int(availability.get("requested_qty") or 0)
    confirmed = int(availability.get("in_stock") or 0)
    shortfall = max(0, int(availability.get("shortfall") or requested - confirmed))
    dependencies = {
        "fulfillment_case": {"id": case_id, "version": str(current.version_id)},
        "atp": str(availability.get("source_version") or "source-version-unavailable"),
        "supplier_schedule": "unconfirmed",
    }
    if delivery_window_days > 0:
        dependencies["operational_calendar"] = str(
            requirements.get("operational_calendar_version") or "calendar-version-unavailable"
        )
    outcome: dict[str, Any] = {"status": "projected"}

    promise: dict[str, Any] | None = None
    if requested_arrival:
        promise = {
            "calculation_version": f"promise-pre-supplier-v1:{current.version_id}",
            "feasibility": "unknown",
            "requested_quantity": requested,
            "requested_arrival_at": requested_arrival,
            "evaluated_at": now,
            "quantity_confirmed_by_deadline": 0,
            "quantity_by_deadline": 0,
            "unknown_quantity": requested,
            "reason_codes": [
                "critical_path_evidence_pending",
                *( ["tenant_operational_calendar_required"] if delivery_window_days else [] ),
                *( ["supplier_confirmation_required"] if shortfall else [] ),
            ],
            "state_prevented": "unsupported_full_delivery_promise",
            "dependency_versions": dependencies,
            "authority": "deterministic_pre_supplier_projection",
        }
        from src.app.services.temporal_authority_repository import record_promise_calculation

        record_promise_calculation(
            db, tenant_id=tenant_id, case_id=case_id, option_id="buyer-commitment",
            result=promise, calculated_at=now,
        )
        outcome["promise"] = promise

    if payment_plan:
        lines = state.get("order_lines") if isinstance(state.get("order_lines"), list) else []
        total, currency = _order_total(db, lines)
        from src.app.services.procurement_payment_consequences import (
            evaluate_payment_consequence,
            record_payment_consequence,
        )

        payment = evaluate_payment_consequence(
            plan_type=payment_plan,
            total_amount_cents=total,
            currency=currency,
            promise_feasibility=str((promise or {}).get("feasibility") or "unknown"),
            policy_version="payment-consequence-v1:tenant-policy-required",
        )
        record_payment_consequence(
            db, tenant_id=tenant_id, case_id=case_id, result=payment, created_at=now,
        )
        outcome["payment"] = payment
    return outcome
