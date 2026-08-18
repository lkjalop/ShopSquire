from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.app.models.orm import Base
from src.app.services.price_forecast_outcomes import (
    persist_price_forecast_candidates,
    project_price_forecast_outcomes,
    settle_price_forecasts_for_purchase,
)


NOW = datetime(2026, 8, 18, 8, 0, tzinfo=timezone.utc)


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def _projection(seasonal=500_000, ewma=510_000):
    return {
        "status": "measured", "currency": "AUD",
        "next_price_minor_units": {"seasonal_naive": seasonal, "ewma": ewma},
    }


def test_forecasts_are_persisted_without_future_actuals():
    db = _db()
    rows = persist_price_forecast_candidates(
        db, tenant_id="portfolio", case_id="case-1", case_revision=4,
        subject_ref="configuration:LAP-1", projection=_projection(),
        source_observation_ids=["price-1", "price-2", "price-3"],
        forecast_created_at=NOW,
    )
    assert len(rows) == 2
    assert {row.status for row in rows} == {"pending"}
    assert {row.actual_minor_units for row in rows} == {None}
    projection = project_price_forecast_outcomes(db, tenant_id="portfolio")
    assert projection["pending_count"] == 2 and projection["settled_count"] == 0


def test_later_server_price_settles_latest_candidate_per_model():
    db = _db()
    persist_price_forecast_candidates(
        db, tenant_id="portfolio", case_id="case-1", case_revision=4,
        subject_ref="configuration:LAP-1", projection=_projection(480_000, 490_000),
        source_observation_ids=["price-1", "price-2", "price-3"],
        forecast_created_at=NOW,
    )
    persist_price_forecast_candidates(
        db, tenant_id="portfolio", case_id="case-1", case_revision=5,
        subject_ref="configuration:LAP-1", projection=_projection(),
        source_observation_ids=["price-2", "price-3", "price-4"],
        forecast_created_at=NOW + timedelta(hours=1),
    )
    receipt = settle_price_forecasts_for_purchase(
        db, tenant_id="portfolio", outcome_id="order-1:paid",
        line_items=[{"sku": "LAP-1", "quantity": 2, "price_cents": 520_000}],
        currency="AUD", observed_at=NOW + timedelta(hours=2),
    )
    assert receipt["settled_count"] == 2
    assert len(receipt["superseded_forecast_ids"]) == 2
    result = project_price_forecast_outcomes(db, tenant_id="portfolio")
    assert result["pending_count"] == 0
    assert result["settled_count"] == result["superseded_count"] == 2
    assert result["mae_minor_units"] == {"ewma": 10_000.0, "seasonal_naive": 20_000.0}
    assert result["causal_claim_authority"] is False


def test_currency_or_sku_mismatch_does_not_settle():
    db = _db()
    persist_price_forecast_candidates(
        db, tenant_id="portfolio", case_id="case-1", case_revision=4,
        subject_ref="configuration:LAP-1", projection=_projection(),
        source_observation_ids=["price-1", "price-2", "price-3"],
        forecast_created_at=NOW,
    )
    receipt = settle_price_forecasts_for_purchase(
        db, tenant_id="portfolio", outcome_id="order-2:paid",
        line_items=[{"sku": "OTHER", "quantity": 1, "price_cents": 1}],
        currency="USD", observed_at=NOW + timedelta(hours=1),
    )
    assert receipt["settled_count"] == 0
    assert project_price_forecast_outcomes(db, tenant_id="portfolio")["pending_count"] == 2
