from src.app.services import market_projection


def test_inventory_without_sales_does_not_become_zero_demand_or_dead_stock(monkeypatch):
    monkeypatch.setattr(market_projection, "load_projection_inputs", lambda *_args, **_kwargs: {
        "sales": [],
        "inventory": [{"sku": "SKU-1", "available": 7, "source_system": "wms",
                       "source_record_id": "stock-1"}],
        "cases": [], "as_of": "2026-08-14T00:00:00Z",
        "sales_status": "insufficient_data", "inventory_status": "observed",
    })
    item = market_projection.projections(object(), tenant_id="tenant-a")["SKU-1"]
    assert item["units_sold"] is None and item["units_per_day"] is None
    assert item["dead_stock"] is None
    assert item["measurement_truth"]["sales"] == "not_collected"
    evidence = market_projection.projection_evidence(
        object(), tenant_id="tenant-a", results=[{"sku": "SKU-1"}],
    )[0]
    assert evidence["forecast_units_30d"] is None
    assert evidence["demand_trend"] == "not_verified"
    assert evidence["bulk_frequency"] is None
    assert evidence["bulk_frequency_state"] == "not_collected"


def test_sales_without_inventory_does_not_become_stockout(monkeypatch):
    monkeypatch.setattr(market_projection, "load_projection_inputs", lambda *_args, **_kwargs: {
        "sales": [{"sku": "SKU-1", "quantity": 3, "source_system": "orders",
                   "source_record_id": "order-1"}],
        "inventory": [], "cases": [], "as_of": "2026-08-14T00:00:00Z",
        "sales_status": "observed", "inventory_status": "unavailable",
    })
    item = market_projection.projections(object(), tenant_id="tenant-a")["SKU-1"]
    assert item["stock_on_hand"] is None and item["stockout"] is None
    assert item["measurement_truth"]["inventory"] == "not_disclosed"
