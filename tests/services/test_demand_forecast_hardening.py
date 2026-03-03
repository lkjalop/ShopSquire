from src.app.services.demand_forecast import DemandForecaster
from src.app.services.inventory_agent import InventoryAgent


def test_demand_forecast_quarantines_untrusted_spikes(monkeypatch):
    fc = DemandForecaster()
    history = [
        {"date": "2026-01-01", "qty": 2, "trust": 1.0, "source": "orders"},
        {"date": "2026-01-02", "qty": 3, "trust": 1.0, "source": "orders"},
        {"date": "2026-01-03", "qty": 90, "trust": 0.2, "source": "supplier_email"},
        {"date": "2026-01-04", "qty": 2, "trust": 1.0, "source": "orders"},
    ]
    monkeypatch.setattr(fc, "_read_history", lambda sku, lookback_days=120: history)
    out = fc.forecast_sku("SKU-1", horizon_days=5)
    assert out.meta is not None
    assert int(out.meta.get("quarantined_points") or 0) >= 1
    assert str(out.meta.get("method") or "")
    assert len(out.daily) == 5


def test_inventory_agent_uses_hardened_pipeline(monkeypatch):
    monkeypatch.setenv("INV_FORECAST_PIPELINE", "1")

    class _FakeForecast:
        daily = [{"mean": 3.0}, {"mean": 4.0}, {"mean": 5.0}]
        meta = {"method": "arima", "quarantined_points": 1, "poison_guard": {"enabled": True}, "mape_proxy": 0.2}

    monkeypatch.setattr(
        "src.app.services.demand_forecast.DemandForecaster.forecast_sku",
        lambda self, sku, horizon_days=14: _FakeForecast(),
    )
    ag = InventoryAgent()
    out = ag._forecast_daily_demand("SKU-2")
    assert out.get("method") == "arima"
    assert int(out.get("quarantined_points") or 0) == 1
    assert out.get("poison_guard")
