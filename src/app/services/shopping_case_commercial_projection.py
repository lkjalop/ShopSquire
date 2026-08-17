"""Run the shared deterministic commercial reducer for one case projection."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from src.app.services.commercial_decision_reducer import (
    CommercialCandidate,
    reduce_commercial_candidate,
)


def _offer_is_current(row: dict[str, Any], evaluation_time: datetime) -> bool:
    value = row.get("validity_expires_at")
    if not value:
        return True
    try:
        expiry = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return False
    return bool(
        expiry.tzinfo is not None
        and expiry.astimezone(timezone.utc) > evaluation_time.astimezone(timezone.utc)
    )


def _deadline_days(
    state_data: dict[str, Any], fulfilment: dict[str, Any], *, evaluation_time: datetime,
) -> int | None:
    explicit = fulfilment.get("deadline_days")
    if isinstance(explicit, int) and not isinstance(explicit, bool) and explicit >= 0:
        return explicit
    temporal = dict(state_data.get("temporal") or {})
    required = temporal.get("required_by")
    if not required:
        return None
    target = datetime.fromisoformat(str(required).replace("Z", "+00:00"))
    if target.tzinfo is None:
        return None
    return max(0, int(
        (target.astimezone(timezone.utc) - evaluation_time.astimezone(timezone.utc)).total_seconds()
        // 86400
    ))


def project_case_commercial_decision(
    *, state_data: dict[str, Any], fulfilment: dict[str, Any],
    evaluation_time: datetime,
) -> dict[str, Any]:
    sku = str(state_data.get("selected_sku") or "").strip()
    requested = state_data.get("requested_quantity")
    if not sku or not isinstance(requested, int):
        return {"status": "not_evaluated", "reason": "sku_or_quantity_missing"}
    offers = [
        row for row in fulfilment.get("offers") or []
        if str(row.get("offered_sku") or "") == sku
        and str(row.get("trust_status") or "unverified") == "trusted"
        and str(row.get("response_status") or "") not in {"rejected", "quarantined"}
        and _offer_is_current(row, evaluation_time)
    ]
    supplier_quantity = sum(int(row.get("quantity_available") or 0) for row in offers)
    lead_times = [int(row["lead_time_days"]) for row in offers if row.get("lead_time_days") is not None]
    price_rows = [row for row in offers if row.get("unit_price_cents") is not None]
    latest_price = fulfilment.get("unit_price_cents")
    unit_price = int(latest_price) if isinstance(latest_price, int) else (
        min(int(row["unit_price_cents"]) for row in price_rows) if price_rows else None
    )
    currency = str(fulfilment.get("currency") or (
        price_rows[0].get("currency") if price_rows else "AUD"
    )).upper()
    budget = dict(state_data.get("budget") or {})
    budget_per_unit = budget.get("amount_minor") if budget.get("scope") == "per_unit" else None
    budget_total = budget.get("amount_minor") if budget.get("scope") == "total" else None
    exact_offer = any(str(row.get("relationship")) == "exact" for row in offers)
    decision = reduce_commercial_candidate(CommercialCandidate(
        sku=sku,
        exact_identity=exact_offer,
        material_unknowns=[] if exact_offer else ["exact configuration identity"],
        specification_freshness="unknown",
        unit_price_cents=unit_price,
        currency=currency,
        budget_per_unit_cents=budget_per_unit,
        budget_total_cents=budget_total,
        requested_quantity=requested,
        local_available_now=(
            int(fulfilment["available_now"]) if fulfilment.get("available_now") is not None else None
        ),
        supplier_quantity=supplier_quantity if offers else None,
        supplier_lead_time_days=max(lead_times) if lead_times else None,
        deadline_days=_deadline_days(
            state_data, fulfilment, evaluation_time=evaluation_time,
        ),
        relationship="exact" if exact_offer else "compatible_substitute",
    ))
    return decision.model_dump(mode="json")


__all__ = ["project_case_commercial_decision"]
