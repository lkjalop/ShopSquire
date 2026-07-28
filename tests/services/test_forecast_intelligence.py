import json
from datetime import date, timedelta

from sqlalchemy import create_engine, text

from src.app.models.db import set_engine
from src.app.services.forecast_intelligence import (
    abc_xyz_segments,
    compare_forecast_models,
    evaluate_inventory_forecast,
)


def _schema(engine):
    with engine.begin() as db:
        db.execute(text("""
            CREATE TABLE marketing_event_fact (
                id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, event_type TEXT NOT NULL,
                sku TEXT, quantity INTEGER, value REAL, source_system TEXT,
                occurred_at TEXT NOT NULL, status TEXT NOT NULL
            )
        """))
        db.execute(text("""
            CREATE TABLE forecast_intelligence_evaluation (
                id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, sku TEXT NOT NULL,
                as_of_date TEXT NOT NULL, horizon_kind TEXT NOT NULL,
                horizon_days INTEGER NOT NULL, history_start TEXT, history_end TEXT,
                source_watermark TEXT, status TEXT NOT NULL, selected_model TEXT,
                abc_class TEXT, xyz_class TEXT, evaluation_json TEXT NOT NULL,
                computation_version TEXT NOT NULL, authority TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """))


def test_model_comparison_has_explicit_metrics_and_lead_time_horizon():
    history = [0, 0, 3, 0, 4, 0, 0] * 8
    result = compare_forecast_models(history, lead_time_days=12.2)
    assert result["horizon"] == {
        "kind": "supplier_lead_time",
        "days": 13,
        "input_days": 12.2,
    }
    assert set(result["models"]) == {
        "seasonal_naive",
        "ewma",
        "croston_sba",
        "tsb",
    }
    for model in result["models"].values():
        assert {"wape", "mase", "bias", "status"} <= set(model)
    assert result["can_increase_autonomy"] is False


def test_abc_xyz_exposes_undefined_and_observed_states():
    segments = abc_xyz_segments(
        {
            "A": [10.0] * 40,
            "B": [0.0, 8.0] * 20,
            "NEW": [1.0] * 10,
        },
        {"A": 900.0, "B": 90.0, "NEW": 10.0},
    )
    assert segments["A"]["abc_class"] == "A"
    assert segments["A"]["xyz_class"] == "X"
    assert segments["NEW"]["xyz_class"] == "undefined"
    assert segments["NEW"]["xyz_status"] == "insufficient_history"


def test_materializes_reconciled_history_idempotently():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    _schema(engine)
    set_engine(engine)
    as_of = date(2026, 7, 28)
    with engine.begin() as db:
        for offset in range(60):
            day = as_of - timedelta(days=59 - offset)
            for sku, quantity, value in (
                ("SKU-A", 5 + (offset % 2), 500 + offset),
                ("SKU-B", 1 if offset % 5 == 0 else 0, 20 if offset % 5 == 0 else 0),
            ):
                db.execute(
                    text(
                        """
                        INSERT INTO marketing_event_fact
                        (id, tenant_id, event_type, sku, quantity, value,
                         source_system, occurred_at, status)
                        VALUES (:id, 'tenant-a', 'purchase', :sku, :qty, :value,
                                'synthetic_reconciled', :day, 'active')
                        """
                    ),
                    {
                        "id": f"{sku}-{offset}",
                        "sku": sku,
                        "qty": quantity,
                        "value": value,
                        "day": day.isoformat(),
                    },
                )
    first = evaluate_inventory_forecast(
        tenant_id="tenant-a",
        sku="SKU-A",
        lead_time_days=9.4,
        lookback_days=60,
        as_of=as_of,
        materialize=True,
    )
    second = evaluate_inventory_forecast(
        tenant_id="tenant-a",
        sku="SKU-A",
        lead_time_days=9.4,
        lookback_days=60,
        as_of=as_of,
        materialize=True,
    )
    assert first["materialized"] is True
    assert first["source"]["kind"] == "reconciled_active_purchase_facts"
    assert first["segmentation"]["abc_class"] == "A"
    assert second["duplicate"] is True
    with engine.connect() as db:
        rows = db.execute(text(
            "SELECT evaluation_json, authority FROM forecast_intelligence_evaluation"
        )).fetchall()
    assert len(rows) == 1
    assert rows[0][1] == "shadow_evaluation_only"
    assert json.loads(rows[0][0])["can_increase_autonomy"] is False
