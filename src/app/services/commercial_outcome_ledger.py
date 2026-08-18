"""Append-only, PII-free realized commercial outcomes for evaluation."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from sqlalchemy import select, text

from src.app.models.orm import CommercialOutcomeRecord


OutcomeType = Literal[
    "order_created", "payment_settled", "cancelled",
    "return_requested", "returned", "satisfaction_recorded",
]


def _utc(value: datetime | None = None) -> datetime:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("commercial_outcome_time_requires_timezone")
    return current.astimezone(timezone.utc)


def record_commercial_outcome(
    db: Any,
    *,
    tenant_id: str,
    outcome_id: str,
    order_id: str,
    outcome_type: OutcomeType,
    source_authority: str,
    trace_id: str | None = None,
    amount_cents: int | None = None,
    currency: str | None = None,
    line_items: list[dict[str, Any]] | None = None,
    observed_at: datetime | None = None,
    effective_at: datetime | None = None,
    commit: bool = True,
) -> CommercialOutcomeRecord:
    """Record an outcome once; this API accepts no buyer identity or address."""

    required = {
        "tenant_id": tenant_id, "outcome_id": outcome_id,
        "order_id": order_id, "source_authority": source_authority,
    }
    missing = sorted(key for key, value in required.items() if not str(value or "").strip())
    if missing:
        raise ValueError(f"commercial_outcome_missing:{','.join(missing)}")
    if amount_cents is not None and amount_cents < 0:
        raise ValueError("commercial_outcome_amount_requires_nonnegative_integer")
    if (amount_cents is None) != (currency is None):
        raise ValueError("commercial_outcome_amount_and_currency_must_coexist")
    safe_lines = []
    for item in line_items or []:
        safe_lines.append({
            "sku": str(item.get("sku") or ""),
            "quantity": max(0, int(item.get("quantity") or 0)),
            "price_cents": max(0, int(item.get("price_cents") or 0)),
        })
    existing = db.execute(select(CommercialOutcomeRecord).where(
        CommercialOutcomeRecord.tenant_id == tenant_id,
        CommercialOutcomeRecord.outcome_id == outcome_id,
    )).scalar_one_or_none()
    if existing is not None:
        return existing
    observed = _utc(observed_at)
    effective = _utc(effective_at or observed)
    row = CommercialOutcomeRecord(
        id=str(uuid.uuid4()), outcome_id=outcome_id, tenant_id=tenant_id,
        order_id=order_id, trace_id=trace_id, outcome_type=outcome_type,
        amount_cents=amount_cents, currency=currency.upper() if currency else None,
        line_items_json=safe_lines, source_authority=source_authority,
        observed_at=observed, effective_at=effective, created_at=_utc(),
    )
    db.add(row)
    if commit:
        db.commit()
    return row


def record_order_transition_outcome(
    db: Any, *, order_id: str, status: str,
) -> CommercialOutcomeRecord | None:
    """Read only server-owned order facts and append their realized outcome."""

    outcome_type = {
        "created": "order_created",
        "paid": "payment_settled",
        "cancelled": "cancelled",
        "return_requested": "return_requested",
        "returned": "returned",
    }.get(status)
    if not outcome_type:
        return None
    row = db.execute(text("""
        SELECT o.tenant_id, o.trace_id, o.total_cents, o.currency, d.line_items
        FROM orders o
        LEFT JOIN draft_orders d ON d.id = o.draft_order_id
        WHERE o.id = :order_id
    """), {"order_id": order_id}).fetchone()
    if not row:
        raise ValueError("commercial_outcome_order_not_found")
    values = row._mapping
    raw_lines = values.get("line_items")
    if isinstance(raw_lines, str):
        raw_lines = json.loads(raw_lines)
    realized = status in {"paid", "returned"}
    observed = datetime.now(timezone.utc)
    outcome = record_commercial_outcome(
        db,
        tenant_id=str(values.get("tenant_id") or "default"),
        outcome_id=f"{order_id}:{status}", order_id=order_id,
        trace_id=values.get("trace_id"), outcome_type=outcome_type,
        amount_cents=int(values.get("total_cents")) if realized else None,
        currency=str(values.get("currency")) if realized else None,
        line_items=list(raw_lines or []),
        source_authority="authenticated_order_transition",
        observed_at=observed,
        commit=False,
    )
    if status == "paid":
        from src.app.services.price_forecast_outcomes import (
            settle_price_forecasts_for_purchase,
        )

        settle_price_forecasts_for_purchase(
            db,
            tenant_id=str(values.get("tenant_id") or "default"),
            outcome_id=f"{order_id}:{status}",
            line_items=list(raw_lines or []),
            currency=str(values.get("currency")),
            observed_at=observed,
            commit=False,
        )
    db.commit()
    return outcome


def project_realized_commercial_outcomes(
    db: Any, *, tenant_id: str, trace_id: str | None = None,
) -> dict[str, Any]:
    query = select(CommercialOutcomeRecord).where(
        CommercialOutcomeRecord.tenant_id == tenant_id,
    )
    if trace_id:
        query = query.where(CommercialOutcomeRecord.trace_id == trace_id)
    rows = db.execute(query.order_by(
        CommercialOutcomeRecord.observed_at.asc(),
        CommercialOutcomeRecord.outcome_id.asc(),
    )).scalars().all()
    settled = [row for row in rows if row.outcome_type == "payment_settled"]
    return {
        "tenant_id": tenant_id,
        "trace_id": trace_id,
        "outcome_count": len(rows),
        "settled_purchase_count": len(settled),
        "settled_value_by_currency": {
            currency: sum(
                int(row.amount_cents or 0) for row in settled if row.currency == currency
            )
            for currency in sorted({row.currency for row in settled if row.currency})
        },
        "outcomes": [{
            "outcome_id": row.outcome_id,
            "order_id": row.order_id,
            "type": row.outcome_type,
            "amount_cents": row.amount_cents,
            "currency": row.currency,
            "line_items": list(row.line_items_json or []),
            "source_authority": row.source_authority,
            "observed_at": row.observed_at.isoformat(),
            "effective_at": row.effective_at.isoformat(),
        } for row in rows],
        "evaluation_authority": "observed_commercial_outcomes",
        "causal_claim_authority": False,
    }


__all__ = [
    "project_realized_commercial_outcomes", "record_commercial_outcome",
    "record_order_transition_outcome",
]
