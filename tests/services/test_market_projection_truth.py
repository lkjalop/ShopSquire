"""Declared simulation stays explicit throughout derived market evidence."""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from src.app.models.db import create_runtime_engine
from src.app.services import market_projection as market


def inputs(status, quantity, available=7):
    return {
        'sales': [] if status == 'insufficient_data' else [
            {'sku': 'TRUTH-SKU', 'quantity': quantity, 'source_system': 'controlled-sales',
             'source_record_id': 'aggregate-1'}],
        'inventory': [{'sku': 'TRUTH-SKU', 'available': available,
            'source_system': 'controlled-stock', 'source_record_id': 'snapshot-1'}],
        'cases': [], 'as_of': datetime.now(timezone.utc).isoformat(),
        'sales_status': status, 'inventory_status': 'observed',
    }


def assert_truth(evidence, status, quantity, available=7):
    assert evidence['source_status']['sales'] == status
    assert evidence['measurement_truth']['sales'] == (
        'not_collected' if status == 'insufficient_data' else status)
    assert evidence['measurement_truth']['inventory'] == 'observed'
    assert evidence['measurement_truth']['authority'] == 'evidence_only'
    if status == 'insufficient_data':
        assert evidence['forecast_units_30d'] is None
        assert evidence['demand_trend'] == 'not_verified'
    else:
        assert evidence['forecast_units_30d'] == quantity
        trend = 'observed_sales' if quantity > 0 else 'dead_stock' if available else 'observed_zero'
        if status == 'simulated':
            trend = 'simulated_sales' if quantity > 0 else 'simulated_dead_stock' if available else 'simulated_zero'
        assert evidence['demand_trend'] == trend
    for metric in evidence['metrics']:
        if metric['metric'] == 'gmroi':
            assert metric['status'] == 'unavailable'
        elif metric['value'] is None:
            assert metric['status'] == 'insufficient_data'
        else:
            assert metric['status'] == ('simulated' if status == 'simulated' else 'estimated')
    assert evidence['economics_included'] is False


@pytest.mark.parametrize('status,quantity,available', [
    ('simulated', 3, 7), ('simulated', 3, 0), ('simulated', 0, 7), ('simulated', 0, 0),
    ('observed', 3, 7), ('observed', 3, 0), ('observed', 0, 7), ('observed', 0, 0),
    ('insufficient_data', 0, 7),
])
def test_projection_keeps_source_truth_in_labels_metrics_and_missingness(monkeypatch, status, quantity, available):
    value = inputs(status, quantity, available)
    monkeypatch.setattr(market, 'load_projection_inputs', lambda *args, **kwargs: value)
    evidence = market.projection_evidence(object(), tenant_id='owned-truth-lab',
        results=[{'sku': 'TRUTH-SKU'}])[0]
    assert_truth(evidence, status, quantity, available)


@pytest.mark.parametrize('quantity', [3, 0])
def test_actual_legacy_demo_rows_cannot_be_relabelled_as_observed_sales(tmp_path, quantity):
    engine = create_runtime_engine('sqlite:///' + (tmp_path / 'projection.sqlite3').as_posix())
    stamp = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    try:
        with Session(engine) as db:
            db.execute(text('CREATE TABLE sales_metrics(sku TEXT,quantity INTEGER,event_time TEXT)'))
            db.execute(text('CREATE TABLE inventory_atp_fact(tenant_id TEXT,sku TEXT,location_id TEXT,'
                'on_hand_quantity INTEGER,committed_quantity INTEGER,confirmed_quantity INTEGER,'
                'observed_at TEXT,source_system TEXT,confidence REAL,source_record_id TEXT,status TEXT)'))
            db.execute(text("INSERT INTO sales_metrics VALUES ('TRUTH-SKU',:quantity,:stamp)"),
                {'quantity': quantity, 'stamp': stamp})
            db.execute(text("INSERT INTO inventory_atp_fact VALUES ('default','TRUTH-SKU','lab',"
                "7,0,7,:stamp,'inventory_level',1,'snapshot-1','active')"), {'stamp': stamp})
            db.commit()
            before = (db.execute(text('SELECT * FROM sales_metrics')).all(),
                db.execute(text('SELECT * FROM inventory_atp_fact')).all())
            evidence = market.projection_evidence(db, tenant_id='default', results=[{'sku': 'TRUTH-SKU'}])[0]
            assert_truth(evidence, 'simulated', quantity)
            after = (db.execute(text('SELECT * FROM sales_metrics')).all(),
                db.execute(text('SELECT * FROM inventory_atp_fact')).all())
            assert after == before
    finally:
        engine.dispose()
