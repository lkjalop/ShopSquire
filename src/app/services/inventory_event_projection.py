"""Pure append-only projection of canonical inventory events.

The projection is deliberately disposable: observations remain the source of
truth and can always rebuild these tenant/location balances. ATP observations
are comparison checkpoints, never balance mutations.
"""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from typing import Any, Iterable

from src.app.services.authoritative_business_feed import (
    BusinessObservation,
    business_observation_id,
)
from src.app.services.business_semantics import validate_payload


BalanceKey = tuple[str, str, str, str]  # variant, location, uom, custody
Effect = dict[BalanceKey, Decimal]
_CUSTODY = ("available", "quarantined", "inspection", "repair", "in_transit",
            "consigned", "unknown")


def _quantity(payload: dict[str, Any]) -> tuple[Decimal, str]:
    quantity = payload["quantity"]
    return Decimal(str(quantity["value"])), str(quantity["uom"])


def _add(effect: Effect, key: BalanceKey, value: Decimal) -> None:
    effect[key] = effect.get(key, Decimal(0)) + value
    if effect[key] == 0:
        effect.pop(key)


def _receipt_bucket(payload: dict[str, Any]) -> str | None:
    custody = str(payload["custody_status"])
    ownership = str(payload["ownership_status"])
    if custody == "rejected":
        return None
    if ownership == "consigned":
        return "consigned"
    if ownership == "unknown":
        return "unknown"
    return {
        "arrived": "inspection",
        "quarantined": "quarantined",
        "accepted": "available",
        "put_away": "available",
    }.get(custody)


def _nominal_effect(
    observation: BusinessObservation,
    payload: dict[str, Any],
    *,
    default_location_id: str,
    receipts: dict[str, dict[str, Any]],
    receipt_buckets: dict[str, str | None],
    transfers: dict[str, dict[str, Any]],
) -> Effect:
    entity = observation.entity_type
    effect: Effect = {}
    if entity == "inventory_adjustment":
        key = (
            str(payload["variant_id"]),
            str(payload["location_id"]),
            str(payload["uom"]),
            "available",
        )
        _add(effect, key, Decimal(str(payload["quantity_delta"])))
    elif entity == "order_line":
        quantity, uom = _quantity(payload)
        key = (
            str(payload["variant_id"]),
            str(payload.get("location_id") or default_location_id),
            uom,
            "available",
        )
        _add(effect, key, -quantity)
    elif entity == "receipt":
        quantity, uom = _quantity(payload)
        bucket = _receipt_bucket(payload)
        if bucket:
            key = (
                str(payload["variant_id"]),
                str(payload["location_id"]),
                uom,
                bucket,
            )
            _add(effect, key, quantity)
        receipt_buckets[observation.external_id] = bucket
    elif entity == "inspection":
        receipt = receipts.get(str(payload["receipt_external_id"]))
        if receipt is None:
            raise ValueError(
                f"inspection_receipt_not_projected:{observation.external_id}"
            )
        quantity, uom = _quantity(payload)
        receipt_id = str(payload["receipt_external_id"])
        source_bucket = receipt_buckets.get(receipt_id, _receipt_bucket(receipt))
        outcome_bucket = {
            "accepted": (
                "consigned"
                if receipt["ownership_status"] == "consigned"
                else "unknown"
                if receipt["ownership_status"] == "unknown"
                else "available"
            ),
            "quarantined": "quarantined",
            "rejected": None,
        }[str(payload["outcome"])]
        location = str(
            payload.get("location_id")
            or receipt["location_id"]
        )
        variant = str(payload["variant_id"])
        if source_bucket:
            _add(effect, (variant, location, uom, source_bucket), -quantity)
        if outcome_bucket:
            _add(effect, (variant, location, uom, outcome_bucket), quantity)
        receipt_buckets[receipt_id] = outcome_bucket
    elif entity == "transfer":
        status = str(payload["status"])
        prior = transfers.get(observation.external_id)
        prior_status = str(prior["status"]) if prior else None
        if status == prior_status:
            return effect
        quantity, uom = _quantity(payload)
        variant = str(payload["variant_id"])
        source = str(payload["from_location_id"])
        destination = str(payload["to_location_id"])
        if status == "in_transit":
            _add(effect, (variant, source, uom, "available"), -quantity)
            _add(effect, (variant, destination, uom, "in_transit"), quantity)
        elif status == "received" and prior_status == "in_transit":
            _add(effect, (variant, destination, uom, "in_transit"), -quantity)
            _add(effect, (variant, destination, uom, "available"), quantity)
        elif status == "received":
            _add(effect, (variant, source, uom, "available"), -quantity)
            _add(effect, (variant, destination, uom, "available"), quantity)
        elif status == "cancelled" and prior_status == "in_transit":
            _add(effect, (variant, destination, uom, "in_transit"), -quantity)
            _add(effect, (variant, source, uom, "available"), quantity)
        transfers[observation.external_id] = payload
    elif entity == "return":
        quantity, uom = _quantity(payload)
        bucket = {
            "restock": "available",
            "quarantine": "quarantined",
            "repair": "repair",
            "scrap": None,
            "return_to_vendor": None,
        }[str(payload["physical_disposition"])]
        if bucket:
            _add(
                effect,
                (
                    str(payload["variant_id"]),
                    str(payload.get("location_id") or default_location_id),
                    uom,
                    bucket,
                ),
                quantity,
            )
    elif entity == "disposal":
        quantity, uom = _quantity(payload)
        _add(
            effect,
            (
                str(payload["variant_id"]),
                str(payload["location_id"]),
                uom,
                str(payload["custody_from"]),
            ),
            -quantity,
        )
    return effect


def _subtract(left: Effect, right: Effect) -> Effect:
    result = dict(left)
    for key, value in right.items():
        _add(result, key, -value)
    return result


def _negate(effect: Effect) -> Effect:
    return {key: -value for key, value in effect.items()}


def _decimal_json(value: Decimal) -> int | float:
    return int(value) if value == value.to_integral_value() else float(value)


def project_inventory_events(
    observations: Iterable[BusinessObservation],
    *,
    tenant_id: str,
    source: str,
    default_location_id: str = "location:primary",
) -> dict[str, Any]:
    """Project one tenant/source stream in event-time order.

    Corrections contribute ``replacement - corrected`` and reversals negate the
    referenced contribution. This preserves every immutable event while making
    replay deterministic and prevents a correction from double-counting stock.
    """
    tenant = str(tenant_id or "").strip()
    source_name = str(source or "").strip().lower()
    if not tenant:
        raise ValueError("projection_tenant_required")
    if not source_name:
        raise ValueError("projection_source_required")
    ordered = sorted(
        list(observations),
        key=lambda row: (row.event_time, row.entity_type, row.external_id),
    )
    balances: defaultdict[BalanceKey, Decimal] = defaultdict(Decimal)
    receipts: dict[str, dict[str, Any]] = {}
    receipt_buckets: dict[str, str | None] = {}
    transfers: dict[str, dict[str, Any]] = {}
    nominal_by_id: dict[str, Effect] = {}
    contribution_by_id: dict[str, Effect] = {}
    checkpoints: list[dict[str, Any]] = []
    event_ledger: list[dict[str, Any]] = []
    internal_failures: list[str] = []
    negative_failures: list[dict[str, Any]] = []

    for observation in ordered:
        payload = validate_payload(
            observation.entity_type,
            dict(observation.payload or {}),
        )
        observation_id = business_observation_id(
            tenant_id=tenant,
            source=source_name,
            observation=observation,
        )
        if observation.entity_type == "location_atp":
            variant = str(payload["variant_id"])
            location = str(payload["location_id"])
            candidates = [
                (uom, value)
                for (row_variant, row_location, uom, custody), value
                in balances.items()
                if row_variant == variant
                and row_location == location
                and custody == "available"
            ]
            candidate_uoms = {uom for uom, _ in candidates}
            projected_uom = next(iter(candidate_uoms)) if len(candidate_uoms) == 1 else (
                str(
                    (payload.get("source_atp") or payload.get("on_hand") or {})
                    .get("uom") or ""
                )
            )
            projected = (
                sum((value for _, value in candidates), Decimal(0))
                if len(candidate_uoms) <= 1
                else None
            )
            source_atp = payload.get("source_atp")
            if source_atp:
                observed = Decimal(str(source_atp["value"]))
                observed_basis = "source_atp"
            elif payload.get("on_hand") and payload.get("committed"):
                observed = (
                    Decimal(str(payload["on_hand"]["value"]))
                    - Decimal(str(payload["committed"]["value"]))
                    + Decimal(str((payload.get("incoming") or {}).get("value", 0)))
                    - Decimal(str((payload.get("safety_stock") or {}).get("value", 0)))
                )
                observed = max(Decimal(0), observed)
                observed_basis = "normalized_source_components"
            else:
                observed = None
                observed_basis = "unavailable"
            observed_uom = str(
                (source_atp or payload.get("on_hand") or {}).get("uom") or ""
            )
            comparable = (
                projected is not None
                and (not projected_uom or projected_uom == observed_uom)
            )
            difference = (
                observed - projected
                if observed is not None and comparable
                else None
            )
            checkpoints.append({
                "observation_id": observation_id,
                "external_id": observation.external_id,
                "event_time": observation.event_time,
                "variant_id": variant,
                "location_id": location,
                "uom": projected_uom,
                "projected_available": (
                    _decimal_json(projected) if projected is not None else None
                ),
                "source_atp": (
                    _decimal_json(observed) if observed is not None else None
                ),
                "source_atp_basis": observed_basis,
                "difference": (
                    _decimal_json(difference)
                    if difference is not None else None
                ),
                "status": (
                    "not_comparable"
                    if not comparable
                    else "matched"
                    if difference == 0
                    else "mismatch"
                    if difference is not None
                    else "unavailable"
                ),
                "reason": (
                    "multiple_projected_uoms"
                    if len(candidate_uoms) > 1
                    else "uom_mismatch"
                    if projected_uom != observed_uom
                    else None
                ),
            })
            continue

        nominal = _nominal_effect(
            observation,
            payload,
            default_location_id=default_location_id,
            receipts=receipts,
            receipt_buckets=receipt_buckets,
            transfers=transfers,
        )
        if observation.corrects_observation_id:
            target = nominal_by_id.get(observation.corrects_observation_id)
            if target is None:
                raise ValueError("projection_correction_target_not_seen")
            contribution = _subtract(nominal, target)
        elif observation.reverses_observation_id:
            target = contribution_by_id.get(observation.reverses_observation_id)
            if target is None:
                raise ValueError("projection_reversal_target_not_seen")
            contribution = _negate(target)
        else:
            contribution = nominal
        nominal_by_id[observation_id] = nominal
        contribution_by_id[observation_id] = contribution
        for key, value in contribution.items():
            balances[key] += value
            if balances[key] < 0:
                negative_failures.append({
                    "observation_id": observation_id,
                    "external_id": observation.external_id,
                    "variant_id": key[0],
                    "location_id": key[1],
                    "uom": key[2],
                    "custody": key[3],
                    "quantity": _decimal_json(balances[key]),
                })
            if balances[key] == 0:
                del balances[key]
        if observation.entity_type == "receipt":
            receipts[observation.external_id] = payload
        movement_total = sum(contribution.values(), Decimal(0))
        if observation.entity_type in {"transfer", "inspection"} and movement_total != 0:
            internal_failures.append(observation.external_id)
        event_ledger.append({
            "observation_id": observation_id,
            "external_id": observation.external_id,
            "entity_type": observation.entity_type,
            "event_kind": (
                "correction" if observation.corrects_observation_id
                else "reversal" if observation.reverses_observation_id
                else "observation"
            ),
            "physical_delta": _decimal_json(movement_total),
            "deltas": [
                {
                    "variant_id": key[0],
                    "location_id": key[1],
                    "uom": key[2],
                    "custody": key[3],
                    "quantity_delta": _decimal_json(value),
                }
                for key, value in sorted(contribution.items())
            ],
        })

    final_negative = [
        {
            "variant_id": key[0],
            "location_id": key[1],
            "uom": key[2],
            "custody": key[3],
            "quantity": _decimal_json(value),
        }
        for key, value in sorted(balances.items())
        if value < 0
    ]
    rows = [
        {
            "tenant_id": tenant,
            "variant_id": key[0],
            "location_id": key[1],
            "uom": key[2],
            "custody": key[3],
            "quantity": _decimal_json(value),
        }
        for key, value in sorted(balances.items())
    ]
    mismatches = [
        row for row in checkpoints if row["status"] in {"mismatch", "not_comparable"}
    ]
    return {
        "tenant_id": tenant,
        "source": source_name,
        "balances": rows,
        "events": event_ledger,
        "atp_reconciliation": {
            "status": "matched" if not mismatches else "mismatch",
            "checkpoints": checkpoints,
            "mismatches": mismatches,
        },
        "conservation": {
            "status": (
                "passed"
                if not internal_failures
                else "failed"
            ),
            "internal_movement_failures": internal_failures,
        },
        "balance_integrity": {
            "status": "passed" if not negative_failures else "failed",
            "negative_balances": negative_failures,
            "final_negative_balances": final_negative,
        },
    }
