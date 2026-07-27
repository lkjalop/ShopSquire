from datetime import datetime, timedelta, timezone
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.app.services.executive_metrics import (
    compare_forecast_candidates_from_sealed,
    forecast_quality_from_sealed,
    persist_forecast_actual_pair,
)


def _db() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    path = (
        Path(__file__).resolve().parents[2]
        / "alembic"
        / "versions"
        / "20260725_forecast_actual_pairs.py"
    )
    spec = spec_from_file_location("forecast_actual_pairs", path)
    migration = module_from_spec(spec)
    spec.loader.exec_module(migration)
    with engine.begin() as connection:
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        path = (
            Path(__file__).resolve().parents[2]
            / "alembic"
            / "versions"
            / "20260728_forecast_candidate_identity.py"
        )
        spec = spec_from_file_location("forecast_candidate_identity", path)
        identity_migration = module_from_spec(spec)
        spec.loader.exec_module(identity_migration)
        identity_migration.op = Operations(MigrationContext.configure(connection))
        identity_migration.upgrade()
    return Session(engine)


def _record(
    db: Session,
    *,
    tenant: str = "t1",
    pair_key: str = "f1",
    model_id: str = "seasonal_naive",
    model_version: str = "v1",
    forecast_value: float = 10,
) -> int:
    now = datetime.now(timezone.utc)
    return persist_forecast_actual_pair(
        db,
        tenant_id=tenant,
        pair_key=pair_key,
        subject_id="SKU-1",
        forecast_value=forecast_value,
        actual_value=8,
        unit="units",
        target_start=now - timedelta(days=7),
        target_end=now,
        forecast_created_at=now - timedelta(days=8),
        actual_observed_at=now,
        source_system="forecast_service",
        source_records=[f"forecast/{pair_key}", f"orders/{pair_key}"],
        provenance_chain=["forecast_service/model-v1", "orders/settled"],
        model_id=model_id,
        model_version=model_version,
        sealed_by="independent-reviewer",
    )


def test_sealed_pairs_are_idempotent_tenant_scoped_quality_evidence():
    db = _db()
    assert _record(db) == 1
    assert _record(db) == 0

    metrics = {row.metric: row for row in forecast_quality_from_sealed(
        db, tenant_id="t1", subject_id="SKU-1")}

    assert metrics["forecast_wape"].value == pytest.approx(0.25)
    assert metrics["forecast_coverage"].value == 1.0
    assert metrics["forecast_wape"].source_records == ["f1"]
    other = forecast_quality_from_sealed(db, tenant_id="t2", subject_id="SKU-1")
    assert all(row.status == "insufficient_data" for row in other)


def test_pair_without_reviewer_or_provenance_is_rejected():
    db = _db()
    now = datetime.now(timezone.utc)
    with pytest.raises(ValueError):
        persist_forecast_actual_pair(
            db,
            tenant_id="t1",
            pair_key="f2",
            subject_id="SKU-1",
            forecast_value=2,
            actual_value=2,
            unit="units",
            target_start=now,
            target_end=now,
            forecast_created_at=now,
            actual_observed_at=now,
            source_system="forecast_service",
            source_records=[],
            provenance_chain=[],
            model_id="seasonal_naive",
            model_version="v1",
            sealed_by="",
        )


def test_sealed_candidate_comparison_is_model_version_scoped_and_shadow_only():
    db = _db()
    assert _record(
        db, pair_key="window-1:baseline", model_id="seasonal_naive",
        forecast_value=12,
    ) == 1
    assert _record(
        db, pair_key="window-1:challenger", model_id="moving_average",
        forecast_value=9,
    ) == 1

    result = compare_forecast_candidates_from_sealed(
        db,
        tenant_id="t1",
        subject_id="SKU-1",
        baseline_model_id="seasonal_naive",
        baseline_model_version="v1",
        challenger_model_id="moving_average",
        challenger_model_version="v1",
        unit_value_cents=5000,
    )

    assert result["status"] == "observed"
    assert result["recommendation"] == "challenger_better"
    assert result["authority"] == "shadow_evaluation_only"
    assert result["baseline_identity"] == {
        "model_id": "seasonal_naive", "model_version": "v1",
    }
    assert result["challenger_identity"] == {
        "model_id": "moving_average", "model_version": "v1",
    }


def test_unsealed_or_other_tenant_pairs_cannot_enter_candidate_comparison():
    db = _db()
    assert _record(
        db, tenant="other", pair_key="other:b", model_id="seasonal_naive",
    ) == 1
    assert _record(
        db, tenant="other", pair_key="other:c", model_id="moving_average",
    ) == 1

    result = compare_forecast_candidates_from_sealed(
        db,
        tenant_id="t1",
        subject_id="SKU-1",
        baseline_model_id="seasonal_naive",
        baseline_model_version="v1",
        challenger_model_id="moving_average",
        challenger_model_version="v1",
    )

    assert result["status"] == "insufficient_data"
    assert result["recommendation"] == "insufficient_data"
