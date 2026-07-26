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


def compare_forecast_candidates(
    *, tenant_id: str, subject_id: str,
    baseline: Sequence[Dict[str, Any]], challenger: Sequence[Dict[str, Any]],
    unit_value_cents: int | None = None, as_of: datetime | None = None,
) -> Dict[str, Any]:
    """Compare two sealed forecast sets without authorizing model promotion."""
    base = {item.metric: item for item in forecast_quality(
        tenant_id=tenant_id, subject_id=subject_id, observations=baseline, as_of=as_of)}
    trial = {item.metric: item for item in forecast_quality(
        tenant_id=tenant_id, subject_id=subject_id, observations=challenger, as_of=as_of)}
    base_wape = base["forecast_wape"].value
    trial_wape = trial["forecast_wape"].value
    measurable = base_wape is not None and trial_wape is not None
    improvement = (float(base_wape) - float(trial_wape)) if measurable else None
    actual_units = sum(
        max(0.0, float(row.get("actual") or 0.0)) for row in challenger
        if row.get("actual") is not None)
    monetary_impact = (
        int(round(abs(float(improvement)) * actual_units * max(0, int(unit_value_cents))))
        if improvement is not None and unit_value_cents is not None else None)
    return {
        "tenant_id": tenant_id,
        "subject_id": subject_id,
        "status": "observed" if measurable else "insufficient_data",
        "baseline": {name: metric.model_dump(mode="json") for name, metric in base.items()},
        "challenger": {name: metric.model_dump(mode="json") for name, metric in trial.items()},
        "wape_improvement": improvement,
        "estimated_absolute_error_value_cents": monetary_impact,
        "recommendation": (
            "challenger_better" if improvement is not None and improvement > 0
            else "baseline_better" if improvement is not None and improvement < 0
            else "no_measurable_difference" if improvement == 0
            else "insufficient_data"
        ),
        "authority": "shadow_evaluation_only",
    }


def persist_forecast_actual_pair(
    db,
    *,
    tenant_id: str,
    pair_key: str,
    subject_id: str,
    forecast_value: float,
    actual_value: float,
    unit: str,
    target_start: datetime,
    target_end: datetime,
    forecast_created_at: datetime,
    actual_observed_at: datetime,
    source_system: str,
    source_records: Sequence[str],
    provenance_chain: Sequence[str],
    sealed_by: str,
    sealed_at: datetime | None = None,
    commit: bool = True,
) -> int:
    """Persist one independently sealed pair; duplicates are idempotent.

    A pair without reviewer identity or provenance is not evidence and is rejected
    before it can affect the forecast-quality snapshot.
    """
    required = {
        "tenant_id": tenant_id,
        "pair_key": pair_key,
        "subject_id": subject_id,
        "unit": unit,
        "source_system": source_system,
        "sealed_by": sealed_by,
    }
    missing = sorted(key for key, value in required.items() if not str(value or "").strip())
    if missing:
        raise ValueError(f"missing forecast pair fields: {','.join(missing)}")
    records = [str(value) for value in source_records if str(value)]
    provenance = [str(value) for value in provenance_chain if str(value)]
    if not records or not provenance:
        raise ValueError("forecast pair requires source records and provenance")
    result = db.execute(text("""
        INSERT INTO forecast_actual_pair (
          id, tenant_id, pair_key, subject_type, subject_id, forecast_value,
          actual_value, unit, target_start, target_end, forecast_created_at,
          actual_observed_at, source_system, source_records_json, provenance_json,
          sealed_at, sealed_by, status
        ) VALUES (
          :id, :tenant, :pair_key, 'sku', :subject_id, :forecast_value,
          :actual_value, :unit, :target_start, :target_end, :forecast_created_at,
          :actual_observed_at, :source_system, :source_records, :provenance,
          :sealed_at, :sealed_by, 'active'
        ) ON CONFLICT(tenant_id, pair_key) DO NOTHING
    """), {
        "id": str(uuid.uuid4()),
        "tenant": str(tenant_id),
        "pair_key": str(pair_key),
        "subject_id": str(subject_id),
        "forecast_value": max(0.0, float(forecast_value)),
        "actual_value": max(0.0, float(actual_value)),
        "unit": str(unit),
        "target_start": target_start,
        "target_end": target_end,
        "forecast_created_at": forecast_created_at,
        "actual_observed_at": actual_observed_at,
        "source_system": str(source_system),
        "source_records": json.dumps(records),
        "provenance": json.dumps(provenance),
        "sealed_at": sealed_at or _now(),
        "sealed_by": str(sealed_by),
    })
    if commit:
        db.commit()
    return max(0, int(result.rowcount or 0))


def forecast_quality_from_sealed(
    db,
    *,
    tenant_id: str,
    subject_id: str,
    as_of: datetime | None = None,
) -> list[MetricEvidence]:
    """Compute quality only from active pairs carrying a durable human seal."""
    rows = db.execute(text("""
        SELECT forecast_value, actual_value, pair_key
        FROM forecast_actual_pair
        WHERE tenant_id=:tenant AND subject_type='sku' AND subject_id=:subject
          AND status='active' AND sealed_by IS NOT NULL AND sealed_by <> ''
        ORDER BY target_end
    """), {"tenant": tenant_id, "subject": subject_id}).fetchall()
    observations = [
        {
            "forecast": float(row[0]),
            "actual": float(row[1]),
            "source_record_id": str(row[2]),
        }
        for row in rows
    ]
    return forecast_quality(
        tenant_id=tenant_id,
        subject_id=subject_id,
        observations=observations,
        as_of=as_of,
    )


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
    wos_sufficient = stock is not None and sold > 0
    turns_sufficient = stock is not None and stock > 0 and sold > 0
    base_reason = None if wos_sufficient else (
        "no_sales_velocity" if stock is not None else "missing_current_atp")
    common = dict(
        tenant_id=tenant_id, subject_type="sku", subject_id=sku,
        as_of=stamp, confidence=min(1.0, len(records) / 2.0),
        source_count=len(set(records)),
        source_records=records, provenance_chain=records,
        definition_version="inventory_productivity_v1", visibility="operator",
        metadata={"inventory_basis": "current_atp_not_average_inventory"},
    )
    return [
        MetricEvidence(
            metric="weeks_of_supply",
            value=(stock / weekly) if wos_sufficient and weekly > 0 else None,
            unit="weeks",
            status="estimated" if wos_sufficient else "insufficient_data",
            coverage=1.0 if wos_sufficient else 0.0,
            reason=base_reason,
            **common),
        MetricEvidence(
            metric="inventory_turns",
            value=(annualized / stock) if turns_sufficient else None,
            unit="turns_per_year",
            status="estimated" if turns_sufficient else "insufficient_data",
            coverage=1.0 if turns_sufficient else 0.0,
            reason=(
                None if turns_sufficient
                else "zero_current_atp_denominator" if stock == 0 and sold > 0
                else base_reason
            ),
            **common),
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
