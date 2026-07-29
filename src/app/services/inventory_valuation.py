"""Authoritative, time-weighted inventory valuation and GMROI evidence.

The append-only business ledger is the authority.  These functions do not
estimate missing landed costs, convert currencies, or authorize an action.
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text

from src.app.schemas.metric_evidence import MetricEvidence


_DEFINITION = "time_weighted_landed_inventory_valuation_v1"


def _utc(value: datetime | str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _unavailable(
    *,
    tenant_id: str,
    variant_id: str,
    window_start: datetime,
    window_end: datetime,
    as_of: datetime,
    reason: str,
    coverage: float = 0.0,
    source_records: list[str] | None = None,
    status: str = "insufficient_data",
    metadata: dict[str, Any] | None = None,
) -> MetricEvidence:
    records = source_records or []
    return MetricEvidence(
        metric="average_landed_inventory_value",
        tenant_id=tenant_id,
        subject_type="variant",
        subject_id=variant_id,
        window_start=window_start,
        window_end=window_end,
        as_of=as_of,
        status=status,
        confidence=0.0,
        coverage=coverage,
        source_count=len(set(records)),
        source_records=records,
        provenance_chain=[f"authoritative_business_observation/{item}" for item in records],
        definition_version=_DEFINITION,
        visibility="operator",
        reason=reason,
        metadata=metadata or {},
    )


def authoritative_average_inventory_valuation(
    db,
    *,
    tenant_id: str,
    source: str,
    variant_id: str,
    window_start: datetime,
    window_end: datetime,
    as_of: datetime | None = None,
    max_snapshot_age: timedelta = timedelta(hours=48),
) -> MetricEvidence:
    """Time-weight accepted landed valuation layers over an explicit window.

    ``observed_at <= as_of`` is the evidence-availability clock.  Corrections
    and reversals visible at that cutoff supersede their targets without
    mutating the ledger.  A baseline at/before the window start and a fresh
    closing snapshot are mandatory; carrying an arbitrarily old point value
    forward would make GMROI look more certain than it is.
    """
    tenant = str(tenant_id or "").strip()
    source_name = str(source or "").strip().lower()
    variant = str(variant_id or "").strip()
    start = _utc(window_start)
    end = _utc(window_end)
    cutoff = _utc(as_of or datetime.now(timezone.utc))
    if not tenant or not source_name or not variant:
        raise ValueError("inventory_valuation_scope_required")
    if end <= start:
        raise ValueError("inventory_valuation_window_invalid")
    if cutoff < end:
        raise ValueError("inventory_valuation_as_of_precedes_window_end")
    if max_snapshot_age.total_seconds() <= 0:
        raise ValueError("inventory_valuation_max_age_invalid")

    rows = db.execute(
        text(
            """
            SELECT id,event_time,observed_at,payload_json,event_kind,
                   corrects_observation_id,reverses_observation_id
            FROM authoritative_business_observation
            WHERE tenant_id=:tenant AND source=:source
              AND entity_type='inventory_valuation'
              AND quality_status='accepted'
              AND event_time<=:window_end AND observed_at<=:as_of
            ORDER BY event_time,observed_at,id
            """
        ),
        {
            "tenant": tenant,
            "source": source_name,
            "window_end": end.isoformat(),
            "as_of": cutoff.isoformat(),
        },
    ).fetchall()
    parsed: list[dict[str, Any]] = []
    for row in rows:
        payload = json.loads(str(row[3]))
        if str(payload.get("variant_id") or "") != variant:
            continue
        parsed.append(
            {
                "id": str(row[0]),
                "event_time": _utc(row[1]),
                "observed_at": _utc(row[2]),
                "payload": payload,
                "event_kind": str(row[4] or "observation"),
                "corrects": str(row[5]) if row[5] else None,
                "reverses": str(row[6]) if row[6] else None,
            }
        )
    if not parsed:
        return _unavailable(
            tenant_id=tenant, variant_id=variant, window_start=start,
            window_end=end, as_of=cutoff, reason="no_authoritative_valuation_observations",
        )

    superseded = {
        target
        for row in parsed
        for target in (row["corrects"], row["reverses"])
        if target
    }
    by_id = {row["id"]: row for row in parsed}
    active = [
        row for row in parsed
        if row["id"] not in superseded and row["event_kind"] != "reversal"
    ]
    # A correction replaces the target at its original effective time.  Its
    # later observed_at still controls when that repaired history is knowable.
    for row in active:
        if row["corrects"] and row["corrects"] in by_id:
            row["event_time"] = by_id[row["corrects"]]["event_time"]
    records = [row["id"] for row in active]
    if not active:
        return _unavailable(
            tenant_id=tenant, variant_id=variant, window_start=start,
            window_end=end, as_of=cutoff, reason="all_valuation_observations_reversed",
            source_records=records,
        )
    if any(row["payload"].get("valuation_basis") != "landed" for row in active):
        return _unavailable(
            tenant_id=tenant, variant_id=variant, window_start=start,
            window_end=end, as_of=cutoff, reason="landed_valuation_basis_required",
            source_records=records, status="unavailable",
        )
    currencies = {
        str(row["payload"]["value"]["currency"]).upper()
        for row in active
    }
    if len(currencies) != 1:
        return _unavailable(
            tenant_id=tenant, variant_id=variant, window_start=start,
            window_end=end, as_of=cutoff, reason="approved_fx_conversion_required",
            source_records=records, status="unavailable",
            metadata={"currencies": sorted(currencies)},
        )

    layer_uoms: dict[tuple[str, str], set[str]] = defaultdict(set)
    for row in active:
        payload = row["payload"]
        layer_uoms[(str(payload["location_id"]), str(payload["layer_ref"]))].add(
            str(payload["quantity"]["uom"]).upper()
        )
    if any(len(units) != 1 for units in layer_uoms.values()):
        return _unavailable(
            tenant_id=tenant, variant_id=variant, window_start=start,
            window_end=end, as_of=cutoff, reason="governed_uom_conversion_required",
            source_records=records, status="unavailable",
        )

    state: dict[tuple[str, str], int] = {}
    for row in active:
        if row["event_time"] > start:
            continue
        payload = row["payload"]
        state[(str(payload["location_id"]), str(payload["layer_ref"]))] = int(
            payload["value"]["amount_minor"]
        )
    if not state:
        first = min(row["event_time"] for row in active)
        coverage = max(0.0, min(1.0, (end - max(start, first)).total_seconds()
                                / (end - start).total_seconds()))
        return _unavailable(
            tenant_id=tenant, variant_id=variant, window_start=start,
            window_end=end, as_of=cutoff, reason="valuation_baseline_before_window_required",
            coverage=coverage, source_records=records,
        )

    by_time: dict[datetime, list[dict[str, Any]]] = defaultdict(list)
    for row in active:
        if start < row["event_time"] <= end:
            by_time[row["event_time"]].append(row)
    cursor = start
    weighted_minor_seconds = 0.0
    for stamp in sorted(by_time):
        weighted_minor_seconds += sum(state.values()) * (stamp - cursor).total_seconds()
        for row in by_time[stamp]:
            payload = row["payload"]
            state[(str(payload["location_id"]), str(payload["layer_ref"]))] = int(
                payload["value"]["amount_minor"]
            )
        cursor = stamp
    weighted_minor_seconds += sum(state.values()) * (end - cursor).total_seconds()

    latest = max(row["event_time"] for row in active)
    age = end - latest
    if age > max_snapshot_age:
        return _unavailable(
            tenant_id=tenant, variant_id=variant, window_start=start,
            window_end=end, as_of=cutoff, reason="closing_valuation_snapshot_stale",
            coverage=max(0.0, min(1.0, 1.0 - age.total_seconds()
                                  / (end - start).total_seconds())),
            source_records=records,
            metadata={
                "latest_event_time": latest.isoformat(),
                "max_snapshot_age_seconds": int(max_snapshot_age.total_seconds()),
            },
        )

    duration = (end - start).total_seconds()
    average = weighted_minor_seconds / duration
    return MetricEvidence(
        metric="average_landed_inventory_value",
        tenant_id=tenant,
        subject_type="variant",
        subject_id=variant,
        value=round(average, 6),
        unit="minor_currency_units",
        currency=next(iter(currencies)),
        window_start=start,
        window_end=end,
        as_of=cutoff,
        status="observed",
        confidence=1.0,
        coverage=1.0,
        source_count=len(set(records)),
        source_records=records,
        provenance_chain=[f"authoritative_business_observation/{item}" for item in records],
        definition_version=_DEFINITION,
        visibility="operator",
        metadata={
            "source": source_name,
            "cost_basis": "landed",
            "valuation_method": "time_weighted_layer_snapshots",
            "latest_event_time": latest.isoformat(),
            "layer_count_at_window_end": len(state),
            "evidence_cutoff": cutoff.isoformat(),
        },
    )


def gmroi_evidence(
    *,
    tenant_id: str,
    variant_id: str,
    gross_margin_minor: int | float | None,
    gross_margin_currency: str | None,
    gross_margin_source_records: list[str],
    average_inventory_valuation: MetricEvidence,
    as_of: datetime | None = None,
) -> MetricEvidence:
    """Annualised gross margin return over authoritative average inventory.

    Gross margin remains an explicit governed input because deriving it from
    sales alone would silently omit returns, markdowns, discounts, and COGS.
    """
    stamp = _utc(as_of or average_inventory_valuation.as_of)
    common = dict(
        metric="gmroi",
        tenant_id=tenant_id,
        subject_type="variant",
        subject_id=variant_id,
        window_start=average_inventory_valuation.window_start,
        window_end=average_inventory_valuation.window_end,
        as_of=stamp,
        definition_version="gmroi_authoritative_v2",
        visibility="operator",
    )
    if (
        average_inventory_valuation.tenant_id != tenant_id
        or average_inventory_valuation.subject_id != variant_id
    ):
        return MetricEvidence(
            **common, status="unavailable", confidence=0.0, coverage=0.0,
            source_count=0, reason="valuation_scope_mismatch",
        )
    if average_inventory_valuation.status != "observed":
        return MetricEvidence(
            **common, status="unavailable", confidence=0.0,
            coverage=average_inventory_valuation.coverage,
            source_count=average_inventory_valuation.source_count,
            source_records=average_inventory_valuation.source_records,
            provenance_chain=average_inventory_valuation.provenance_chain,
            reason="authoritative_average_inventory_valuation_required",
        )
    currency = str(gross_margin_currency or "").upper()
    if not currency or currency != average_inventory_valuation.currency:
        return MetricEvidence(
            **common, status="unavailable", confidence=0.0, coverage=0.0,
            source_count=average_inventory_valuation.source_count,
            source_records=average_inventory_valuation.source_records,
            provenance_chain=average_inventory_valuation.provenance_chain,
            reason="gross_margin_currency_mismatch",
        )
    if gross_margin_minor is None or not gross_margin_source_records:
        return MetricEvidence(
            **common, status="insufficient_data", confidence=0.0, coverage=0.0,
            source_count=average_inventory_valuation.source_count,
            source_records=average_inventory_valuation.source_records,
            provenance_chain=average_inventory_valuation.provenance_chain,
            reason="governed_gross_margin_evidence_required",
        )
    denominator = float(average_inventory_valuation.value or 0.0)
    if denominator <= 0:
        return MetricEvidence(
            **common, status="insufficient_data", confidence=0.0, coverage=1.0,
            source_count=average_inventory_valuation.source_count,
            source_records=average_inventory_valuation.source_records,
            provenance_chain=average_inventory_valuation.provenance_chain,
            reason="zero_average_inventory_valuation_denominator",
        )
    start = average_inventory_valuation.window_start
    end = average_inventory_valuation.window_end
    if start is None or end is None:
        raise ValueError("gmroi_valuation_window_required")
    window_days = (end - start).total_seconds() / 86400.0
    value = float(gross_margin_minor) * (365.0 / window_days) / denominator
    valuation_records = average_inventory_valuation.source_records
    margin_records = [str(item) for item in gross_margin_source_records if str(item)]
    return MetricEvidence(
        **common,
        value=round(value, 6),
        unit="annualised_ratio",
        currency=currency,
        status="observed",
        confidence=min(average_inventory_valuation.confidence, 1.0),
        coverage=average_inventory_valuation.coverage,
        source_count=len(set([*valuation_records, *margin_records])),
        source_records=[*valuation_records, *margin_records],
        provenance_chain=[
            *average_inventory_valuation.provenance_chain,
            *(f"governed_gross_margin/{item}" for item in margin_records),
        ],
        metadata={
            "gross_margin_minor": float(gross_margin_minor),
            "average_inventory_value_minor": denominator,
            "annualisation_days": 365,
            "cost_basis": "landed",
            "authority": "metric_evidence_only",
        },
    )
