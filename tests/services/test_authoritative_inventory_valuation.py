from __future__ import annotations

import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine

from src.app.models.db import set_engine
from src.app.services.authoritative_business_feed import (
    BusinessObservation,
    business_observation_id,
    ingest_authoritative_observations,
)
from src.app.services.inventory_valuation import (
    authoritative_average_inventory_valuation,
    gmroi_evidence,
)

# Keep the evidence cutoff deterministically after every observation created by
# these fixtures. A wall-clock-adjacent date makes this suite expire and causes
# the bitemporal query to correctly hide freshly ingested hosted-runner rows.
_CUTOFF = datetime(2100, 1, 1, tzinfo=timezone.utc)


def _apply_migrations(engine) -> None:
    for filename in (
        "20260809_authoritative_business_feed.py",
        "20260813_canonical_business_semantics.py",
    ):
        path = Path(__file__).resolve().parents[2] / "alembic" / "versions" / filename
        spec = importlib.util.spec_from_file_location(filename.replace(".", "_"), path)
        module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(module)
        with engine.begin() as connection:
            operations = Operations(MigrationContext.configure(connection))
            original = module.op
            module.op = operations
            try:
                module.upgrade()
            finally:
                module.op = original


def _valuation(
    external_id: str,
    event_time: datetime,
    value: int,
    *,
    currency: str = "AUD",
    basis: str = "landed",
    variant: str = "variant-1",
    corrects: str | None = None,
    reverses: str | None = None,
) -> BusinessObservation:
    return BusinessObservation(
        entity_type="inventory_valuation",
        external_id=external_id,
        event_time=event_time.isoformat(),
        payload={
            "variant_id": variant,
            "location_id": "loc-1",
            "quantity": {"value": 10, "uom": "EA"},
            "value": {"amount_minor": value, "currency": currency},
            "costing_method": "fifo",
            "layer_ref": "layer-1",
            "valuation_basis": basis,
        },
        corrects_observation_id=corrects,
        reverses_observation_id=reverses,
    )


@pytest.fixture
def valuation_db(tmp_path):
    engine = create_engine(
        f"sqlite+pysqlite:///{tmp_path / 'valuation.sqlite'}", future=True
    )
    _apply_migrations(engine)
    set_engine(engine)
    return engine


def test_time_weighted_landed_valuation_and_gmroi_are_observed(valuation_db):
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    end = start + timedelta(days=10)
    observations = [
        _valuation("v1", start, 10_000),
        _valuation("v2", start + timedelta(days=5), 20_000),
        _valuation("v3", end, 20_000),
    ]
    assert ingest_authoritative_observations(
        tenant_id="tenant-a", source="erp", observations=observations
    )["records_inserted"] == 3
    with valuation_db.connect() as db:
        valuation = authoritative_average_inventory_valuation(
            db, tenant_id="tenant-a", source="erp", variant_id="variant-1",
            window_start=start, window_end=end, as_of=_CUTOFF,
        )
    assert valuation.status == "observed"
    assert valuation.value == 15_000
    assert valuation.currency == "AUD"
    assert valuation.metadata["cost_basis"] == "landed"

    gmroi = gmroi_evidence(
        tenant_id="tenant-a", variant_id="variant-1",
        gross_margin_minor=3_000, gross_margin_currency="AUD",
        gross_margin_source_records=["margin-ledger/window-1"],
        average_inventory_valuation=valuation,
    )
    assert gmroi.status == "observed"
    assert gmroi.value == pytest.approx(7.3)
    assert gmroi.metadata["authority"] == "metric_evidence_only"


def test_valuation_is_tenant_scoped_and_requires_a_window_baseline(valuation_db):
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    end = start + timedelta(days=10)
    assert ingest_authoritative_observations(
        tenant_id="tenant-b", source="erp",
        observations=[_valuation("other", start, 99_000)]
    )["records_inserted"] == 1
    assert ingest_authoritative_observations(
        tenant_id="tenant-a", source="erp",
        observations=[_valuation("late", start + timedelta(days=5), 10_000)]
    )["records_inserted"] == 1
    with valuation_db.connect() as db:
        result = authoritative_average_inventory_valuation(
            db, tenant_id="tenant-a", source="erp", variant_id="variant-1",
            window_start=start, window_end=end, as_of=_CUTOFF,
            max_snapshot_age=timedelta(days=10),
        )
    assert result.status == "insufficient_data"
    assert result.reason == "valuation_baseline_before_window_required"
    assert result.coverage == 0.5
    assert result.source_count == 1


@pytest.mark.parametrize(
    ("basis", "currency", "reason"),
    [
        ("product_cost_only", "AUD", "landed_valuation_basis_required"),
        ("landed", "USD", "approved_fx_conversion_required"),
    ],
)
def test_gmroi_fails_closed_for_non_landed_or_mixed_currency(
    valuation_db, basis, currency, reason
):
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    end = start + timedelta(days=2)
    rows = [
        _valuation("base", start, 10_000, basis=basis),
        _valuation("close", end, 10_000, basis=basis, currency=currency),
    ]
    ingest_authoritative_observations(
        tenant_id="tenant-a", source="erp", observations=rows
    )
    with valuation_db.connect() as db:
        valuation = authoritative_average_inventory_valuation(
            db, tenant_id="tenant-a", source="erp", variant_id="variant-1",
            window_start=start, window_end=end, as_of=_CUTOFF,
        )
    assert valuation.status == "unavailable"
    assert valuation.reason == reason


def test_stale_closing_snapshot_blocks_gmroi(valuation_db):
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    end = start + timedelta(days=10)
    ingest_authoritative_observations(
        tenant_id="tenant-a", source="erp",
        observations=[_valuation("base", start, 10_000)]
    )
    with valuation_db.connect() as db:
        valuation = authoritative_average_inventory_valuation(
            db, tenant_id="tenant-a", source="erp", variant_id="variant-1",
            window_start=start, window_end=end, as_of=_CUTOFF,
        )
    assert valuation.status == "insufficient_data"
    assert valuation.reason == "closing_valuation_snapshot_stale"
    gmroi = gmroi_evidence(
        tenant_id="tenant-a", variant_id="variant-1",
        gross_margin_minor=1_000, gross_margin_currency="AUD",
        gross_margin_source_records=["margin/1"],
        average_inventory_valuation=valuation,
    )
    assert gmroi.status == "unavailable"
    assert gmroi.reason == "authoritative_average_inventory_valuation_required"


def test_append_only_correction_replaces_value_at_original_effective_time(
    valuation_db,
):
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    end = start + timedelta(days=2)
    original = _valuation("base", start, 10_000)
    original_id = business_observation_id(
        tenant_id="tenant-a", source="erp", observation=original
    )
    corrected = _valuation(
        "base-correction", start + timedelta(hours=1), 12_000,
        corrects=original_id,
    )
    ingest_authoritative_observations(
        tenant_id="tenant-a", source="erp",
        observations=[original, corrected, _valuation("close", end, 12_000)],
    )
    with valuation_db.connect() as db:
        result = authoritative_average_inventory_valuation(
            db, tenant_id="tenant-a", source="erp", variant_id="variant-1",
            window_start=start, window_end=end, as_of=_CUTOFF,
        )
    assert result.status == "observed"
    assert result.value == 12_000
    assert original_id not in result.source_records
