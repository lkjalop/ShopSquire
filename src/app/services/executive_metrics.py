"""Portable executive metrics over governed facts.

Every result carries status and provenance. This module computes evidence; it
does not authorize prices, purchases, supplier messages, or rankings.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Sequence

from sqlalchemy import text

from src.app.schemas.metric_evidence import MetricEvidence


def _now() -> datetime:
    return datetime.now(timezone.utc)


def forecast_quality(
    *, tenant_id: str, subject_id: str, observations: Sequence[Dict[str, Any]],
    visibility: str = "operator", as_of: datetime | None = None,
) -> list[MetricEvidence]:
    """Evaluate sealed forecast/actual pairs using zero-safe retail metrics."""
    pairs = []
    for row in observations:
        try:
            forecast = max(0.0, float(row["forecast"]))
            actual = max(0.0, float(row["actual"]))
        except (KeyError, TypeError, ValueError):
            continue
        pairs.append((forecast, actual, str(row.get("source_record_id") or "")))
    stamp = as_of or _now()
    coverage = len(pairs) / max(1, len(observations))
    if not pairs:
        return [MetricEvidence(
            metric=name, tenant_id=tenant_id, subject_type="sku",
            subject_id=subject_id, as_of=stamp, status="insufficient_data",
            confidence=0.0, coverage=coverage, source_count=0,
            definition_version="retail_forecast_v1", visibility=visibility,
            reason="no_matched_forecast_actual_pairs",
        ) for name in ("forecast_wape", "forecast_bias", "forecast_coverage")]
    abs_error = sum(abs(forecast - actual) for forecast, actual, _ in pairs)
    signed_error = sum(forecast - actual for forecast, actual, _ in pairs)
    actual_total = sum(actual for _forecast, actual, _ in pairs)
    source_records = [record for _f, _a, record in pairs if record]
    confidence = min(1.0, len(pairs) / 12.0)
    common = dict(
        tenant_id=tenant_id, subject_type="sku", subject_id=subject_id,
        as_of=stamp, status="observed", confidence=confidence,
        coverage=coverage, source_count=len(set(source_records)),
        source_records=source_records,
        provenance_chain=[f"forecast_actual/{record}" for record in source_records],
        definition_version="retail_forecast_v1", visibility=visibility,
    )
    denominator = actual_total if actual_total > 0 else None
    return [
        MetricEvidence(
            metric="forecast_wape",
            value=(abs_error / denominator) if denominator else None, unit="ratio",
            reason=None if denominator else "zero_actual_denominator", **common),
        MetricEvidence(
            metric="forecast_bias",
            value=(signed_error / denominator) if denominator else None, unit="ratio",
            reason=None if denominator else "zero_actual_denominator", **common),
        MetricEvidence(
            metric="forecast_coverage", value=coverage, unit="ratio", **common),
    ]


def inventory_productivity(
    *, tenant_id: str, sku: str, units_sold: int, window_days: int,
    available_units: int | None, source_records: Iterable[str] = (),
    as_of: datetime | None = None,
) -> list[MetricEvidence]:
    """Estimate WOS and turns from canonical sales plus a point-in-time ATP balance."""
    stamp = as_of or _now()
    records = [str(record) for record in source_records if str(record)]
    days = max(1, int(window_days))
    sold = max(0, int(units_sold))
    stock = max(0, int(available_units)) if available_units is not None else None
    weekly = sold * 7.0 / days
    annualized = sold * 365.0 / days
    sufficient = stock is not None and sold > 0
    status = "estimated" if sufficient else "insufficient_data"
    reason = None if sufficient else (
        "no_sales_velocity" if stock is not None else "missing_current_atp")
    common = dict(
        tenant_id=tenant_id, subject_type="sku", subject_id=sku,
        as_of=stamp, status=status, confidence=min(1.0, len(records) / 2.0),
        coverage=1.0 if sufficient else 0.0, source_count=len(set(records)),
        source_records=records, provenance_chain=records,
        definition_version="inventory_productivity_v1", visibility="operator",
        reason=reason,
        metadata={"inventory_basis": "current_atp_not_average_inventory"},
    )
    return [
        MetricEvidence(
            metric="weeks_of_supply",
            value=(stock / weekly) if sufficient and weekly > 0 else None,
            unit="weeks", **common),
        MetricEvidence(
            metric="inventory_turns",
            value=(annualized / stock) if sufficient and stock > 0 else None,
            unit="turns_per_year", **common),
    ]


def ppv_evidence(
    *, tenant_id: str, sku: str, quote: Dict[str, Any] | None,
    purchase_order: Dict[str, Any] | None, invoice: Dict[str, Any] | None,
) -> MetricEvidence:
    """Return PPV only when quote, PO, and invoice share an explicit identity."""
    records = [quote or {}, purchase_order or {}, invoice or {}]
    identity = {str(row.get("match_id") or "") for row in records}
    currencies = {str(row.get("currency") or "").upper() for row in records}
    matched = len(identity) == 1 and "" not in identity and len(currencies) == 1 and "" not in currencies
    values = [row.get("unit_cost_cents") for row in records]
    if not matched or any(value is None for value in values):
        return MetricEvidence(
            metric="purchase_price_variance", tenant_id=tenant_id,
            subject_type="sku", subject_id=sku, as_of=_now(),
            status="unavailable", confidence=0.0, coverage=0.0, source_count=0,
            definition_version="matched_document_ppv_v1", visibility="operator",
            reason="matched_quote_po_invoice_required")
    quote_cost, _po_cost, invoice_cost = (int(value) for value in values)
    return MetricEvidence(
        metric="purchase_price_variance", tenant_id=tenant_id,
        subject_type="sku", subject_id=sku, value=invoice_cost - quote_cost,
        unit="minor_currency_units", currency=next(iter(currencies)), as_of=_now(),
        status="observed", confidence=1.0, coverage=1.0, source_count=3,
        source_records=[f"{row['match_id']}:{kind}" for row, kind in zip(
            records, ("quote", "po", "invoice"))],
        provenance_chain=[str(row.get("provenance") or "") for row in records],
        definition_version="matched_document_ppv_v1", visibility="operator")


def gmroi_unavailable(*, tenant_id: str, subject_id: str) -> MetricEvidence:
    return MetricEvidence(
        metric="gmroi", tenant_id=tenant_id, subject_type="sku",
        subject_id=subject_id, as_of=_now(), status="unavailable",
        confidence=0.0, coverage=0.0, source_count=0,
        definition_version="gmroi_v1", visibility="operator",
        reason="average_landed_cost_inventory_valuation_required")


def persist_metric(db, evidence: MetricEvidence, *, commit: bool = True) -> None:
    payload = evidence.model_dump(mode="json")
    db.execute(text("""
        INSERT INTO executive_metric_snapshot (
          id, tenant_id, metric_name, subject_type, subject_id, value_numeric,
          unit, currency, window_start, window_end, as_of, status, confidence,
          coverage, source_count, source_records_json, provenance_json,
          definition_version, visibility, reason, metadata_json
        ) VALUES (
          :id, :tenant_id, :metric, :subject_type, :subject_id, :value,
          :unit, :currency, :window_start, :window_end, :as_of, :status, :confidence,
          :coverage, :source_count, :source_records, :provenance,
          :definition_version, :visibility, :reason, :metadata
        ) ON CONFLICT(tenant_id, metric_name, subject_type, subject_id, as_of) DO NOTHING
    """), {
        **payload, "id": str(uuid.uuid4()),
        "source_records": json.dumps(payload["source_records"]),
        "provenance": json.dumps(payload["provenance_chain"]),
        "metadata": json.dumps(payload["metadata"]),
    })
    if commit:
        db.commit()
