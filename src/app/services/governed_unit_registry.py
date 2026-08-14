"""Reviewed units and evidence-gated currency conversion."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class FxRateEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    base_currency: str = Field(min_length=3, max_length=3)
    quote_currency: str = Field(min_length=3, max_length=3)
    rate: Decimal = Field(gt=0)
    observed_at: datetime
    source_authority: str = Field(min_length=1, max_length=200)
    source_record_id: str = Field(min_length=1, max_length=200)


class UnitConversionReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["governed-unit-conversion-v1"] = "governed-unit-conversion-v1"
    input_value: Decimal
    input_unit: str
    output_value: Decimal
    output_unit: str
    dimension: str
    method: Literal["reviewed_factor", "timestamped_fx", "identity"]
    source_authority: str
    observed_at: datetime | None = None
    authority: Literal["conversion_only"] = "conversion_only"


@lru_cache(maxsize=1)
def load_unit_registry() -> dict:
    path = Path(__file__).resolve().parents[3] / "config" / "governed_units.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    if int(payload.get("version") or 0) != 1:
        raise ValueError("unsupported_unit_registry_version")
    return payload


def _unit_candidates(unit: str) -> list[tuple[str, Decimal]]:
    needle = str(unit or "").strip()
    matches: list[tuple[str, Decimal]] = []
    for dimension, config in load_unit_registry()["dimensions"].items():
        for name, factor in config["units"].items():
            if needle == name or needle.lower() == name.lower():
                matches.append((dimension, Decimal(str(factor))))
    if not matches:
        raise ValueError(f"unknown_unit:{needle}")
    return matches


def convert_measurement(value: Decimal | int | float | str, from_unit: str,
                        to_unit: str) -> UnitConversionReceipt:
    sources = _unit_candidates(from_unit)
    targets = _unit_candidates(to_unit)
    shared = [(dimension, source_factor, target_factor)
              for dimension, source_factor in sources
              for target_dimension, target_factor in targets
              if dimension == target_dimension]
    if len(shared) != 1:
        source_names = ",".join(dimension for dimension, _ in sources)
        target_names = ",".join(dimension for dimension, _ in targets)
        raise ValueError(f"unit_dimension_mismatch:{source_names}:{target_names}")
    source_dimension, source_factor, target_factor = shared[0]
    amount = Decimal(str(value))
    return UnitConversionReceipt(
        input_value=amount, input_unit=from_unit,
        output_value=(amount * source_factor / target_factor), output_unit=to_unit,
        dimension=source_dimension,
        method="identity" if from_unit == to_unit else "reviewed_factor",
        source_authority="config/governed_units.json:v1",
    )


def convert_currency(value: Decimal | int | float | str, from_currency: str,
                     to_currency: str, *, rate_evidence: FxRateEvidence | None = None,
                     max_age_hours: int = 24, now: datetime | None = None) -> UnitConversionReceipt:
    source = str(from_currency).upper()
    target = str(to_currency).upper()
    allowed = set(load_unit_registry()["currency"]["codes"])
    if source not in allowed or target not in allowed:
        raise ValueError("unsupported_currency")
    amount = Decimal(str(value))
    if source == target:
        return UnitConversionReceipt(
            input_value=amount, input_unit=source, output_value=amount, output_unit=target,
            dimension="currency", method="identity", source_authority="currency_identity",
        )
    if rate_evidence is None:
        raise ValueError("timestamped_fx_rate_required")
    if rate_evidence.base_currency.upper() != source or rate_evidence.quote_currency.upper() != target:
        raise ValueError("fx_rate_pair_mismatch")
    observed = rate_evidence.observed_at
    if observed.tzinfo is None:
        observed = observed.replace(tzinfo=timezone.utc)
    current = now or datetime.now(timezone.utc)
    if (current - observed.astimezone(timezone.utc)).total_seconds() > max(1, max_age_hours) * 3600:
        raise ValueError("fx_rate_stale")
    return UnitConversionReceipt(
        input_value=amount, input_unit=source,
        output_value=amount * rate_evidence.rate, output_unit=target,
        dimension="currency", method="timestamped_fx",
        source_authority=rate_evidence.source_authority, observed_at=observed,
    )


__all__ = [
    "FxRateEvidence", "UnitConversionReceipt", "convert_currency",
    "convert_measurement", "load_unit_registry",
]
