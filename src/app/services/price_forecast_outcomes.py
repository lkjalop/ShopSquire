"""Leakage-safe forecast persistence and settlement from observed purchases."""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from src.app.models.orm import PriceForecastCandidateRecord


MODEL_VERSION = "causal-baseline-v1"


def _utc(value: datetime | None = None) -> datetime:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("price_forecast_time_requires_timezone")
    return current.astimezone(timezone.utc)


def _identity(value: str) -> str:
    normalized = str(value or "").strip().lower()
    for prefix in ("configuration:", "sku:"):
        if normalized.startswith(prefix):
            return normalized[len(prefix):]
    return normalized


def persist_price_forecast_candidates(
    db: Any,
    *,
    tenant_id: str,
    case_id: str,
    case_revision: int,
    subject_ref: str,
    projection: dict[str, Any],
    source_observation_ids: list[str],
    forecast_created_at: datetime,
    commit: bool = True,
) -> list[PriceForecastCandidateRecord]:
    """Fix predictions now; actuals are deliberately absent until later settlement."""

    predictions = projection.get("next_price_minor_units") or {}
    currency = str(projection.get("currency") or "").upper()
    if projection.get("status") != "measured" or not predictions or not currency:
        return []
    now = _utc(forecast_created_at)
    source_ids = sorted({str(value) for value in source_observation_ids if str(value)})
    if not source_ids:
        raise ValueError("price_forecast_requires_source_observations")
    created = []
    for model_id, predicted in sorted(predictions.items()):
        predicted_value = max(0, int(round(float(predicted))))
        material = {
            "tenant": tenant_id, "case": case_id, "revision": case_revision,
            "subject": subject_ref, "model": model_id, "version": MODEL_VERSION,
            "sources": source_ids, "created_at": now.isoformat(),
        }
        forecast_id = "price-forecast:" + hashlib.sha256(json.dumps(
            material, sort_keys=True, separators=(",", ":"),
        ).encode()).hexdigest()[:32]
        existing = db.execute(select(PriceForecastCandidateRecord).where(
            PriceForecastCandidateRecord.tenant_id == tenant_id,
            PriceForecastCandidateRecord.forecast_id == forecast_id,
        )).scalar_one_or_none()
        if existing is not None:
            created.append(existing)
            continue
        row = PriceForecastCandidateRecord(
            id=str(uuid.uuid4()), forecast_id=forecast_id, tenant_id=tenant_id,
            case_id=case_id, case_revision=case_revision, subject_ref=subject_ref,
            model_id=str(model_id), model_version=MODEL_VERSION,
            predicted_minor_units=predicted_value, currency=currency,
            source_observation_ids_json=source_ids, forecast_created_at=now,
            target_semantics="next_observed_unit_price",
            status="pending", settled_outcome_id=None, actual_minor_units=None,
            actual_observed_at=None, absolute_error_minor_units=None,
            created_at=now, updated_at=now,
        )
        db.add(row)
        created.append(row)
    if commit:
        db.commit()
    return created


def settle_price_forecasts_for_purchase(
    db: Any,
    *,
    tenant_id: str,
    outcome_id: str,
    line_items: list[dict[str, Any]],
    currency: str,
    observed_at: datetime,
    commit: bool = True,
) -> dict[str, Any]:
    """Settle the latest pending candidate per SKU/model from server prices."""

    observed = _utc(observed_at)
    target_currency = str(currency or "").upper()
    settled: list[str] = []
    superseded: list[str] = []
    for item in line_items:
        sku = _identity(str(item.get("sku") or ""))
        if not sku:
            continue
        actual = max(0, int(item.get("price_cents") or 0))
        pending = db.execute(select(PriceForecastCandidateRecord).where(
            PriceForecastCandidateRecord.tenant_id == tenant_id,
            PriceForecastCandidateRecord.currency == target_currency,
            PriceForecastCandidateRecord.status == "pending",
            PriceForecastCandidateRecord.forecast_created_at <= observed,
        ).order_by(PriceForecastCandidateRecord.forecast_created_at.desc())).scalars().all()
        matching = [row for row in pending if _identity(row.subject_ref) == sku]
        latest_by_model: dict[str, PriceForecastCandidateRecord] = {}
        for row in matching:
            if row.model_id not in latest_by_model:
                latest_by_model[row.model_id] = row
            else:
                row.status = "superseded"
                row.updated_at = observed
                superseded.append(row.forecast_id)
        for row in latest_by_model.values():
            row.status = "settled"
            row.settled_outcome_id = outcome_id
            row.actual_minor_units = actual
            row.actual_observed_at = observed
            row.absolute_error_minor_units = abs(row.predicted_minor_units - actual)
            row.updated_at = observed
            settled.append(row.forecast_id)
    if commit:
        db.commit()
    return {
        "outcome_id": outcome_id,
        "settled_forecast_ids": sorted(settled),
        "superseded_forecast_ids": sorted(superseded),
        "settled_count": len(settled),
        "authority": "observed_server_price",
        "causal_claim_authority": False,
    }


def project_price_forecast_outcomes(db: Any, *, tenant_id: str) -> dict[str, Any]:
    rows = db.execute(select(PriceForecastCandidateRecord).where(
        PriceForecastCandidateRecord.tenant_id == tenant_id,
    )).scalars().all()
    settled = [row for row in rows if row.status == "settled"]
    by_model: dict[str, list[int]] = {}
    for row in settled:
        by_model.setdefault(row.model_id, []).append(int(row.absolute_error_minor_units or 0))
    return {
        "tenant_id": tenant_id,
        "candidate_count": len(rows),
        "pending_count": sum(row.status == "pending" for row in rows),
        "settled_count": len(settled),
        "superseded_count": sum(row.status == "superseded" for row in rows),
        "mae_minor_units": {
            model: round(sum(errors) / len(errors), 4)
            for model, errors in sorted(by_model.items()) if errors
        },
        "evaluation_semantics": "prediction_persisted_before_payment_actual",
        "causal_claim_authority": False,
    }


__all__ = [
    "persist_price_forecast_candidates", "project_price_forecast_outcomes",
    "settle_price_forecasts_for_purchase",
]
