from contextlib import contextmanager

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import OperationalError


class _MissingForecastSchema:
    def execute(self, *_args, **_kwargs):
        raise OperationalError("select", {}, Exception("no such column: model_id"))


def test_forecast_comparison_reports_migration_required_instead_of_500(monkeypatch):
    from src.app.routers import admin_bi

    @contextmanager
    def _db():
        yield _MissingForecastSchema()

    monkeypatch.setattr(admin_bi, "db_session", _db)

    with pytest.raises(HTTPException) as caught:
        admin_bi.executive_metric_forecast_comparison(
            sku="SKU-1",
            baseline_model_id="seasonal_naive",
            baseline_model_version="v1",
            challenger_model_id="moving_average",
            challenger_model_version="v1",
            unit_value_cents=None,
            role="OWNER",
        )

    assert caught.value.status_code == 503
    assert caught.value.detail == (
        "forecast_evidence_schema_unavailable_apply_alembic_head"
    )
