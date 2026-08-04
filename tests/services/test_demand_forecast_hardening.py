from src.app.services.demand_forecast import DemandForecaster
from src.app.services.inventory_agent import InventoryAgent
from contextlib import contextmanager
from datetime import datetime, timezone


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
    captured = {}

    def _init(self, *, tenant_id="default"):
        captured["tenant_id"] = tenant_id

    monkeypatch.setattr(
        "src.app.services.demand_forecast.DemandForecaster.__init__", _init
    )
    ag = InventoryAgent(tenant_id="tenant-b")
    out = ag._forecast_daily_demand("SKU-2")
    assert captured["tenant_id"] == "tenant-b"
    assert out.get("method") == "arima"
    assert int(out.get("quarantined_points") or 0) == 1
    assert out.get("poison_guard")


def test_history_reads_tenant_scoped_canonical_purchase_facts(monkeypatch):
    captured = {}

    class _Result:
        def fetchall(self):
            return [
                ("2026-07-20T02:00:00Z", 2, 1.0, "orders"),
                ("2026-07-20T08:00:00Z", 3, 0.8, "shopify"),
                ("2026-07-21T02:00:00Z", 4, 1.0, "orders"),
            ]

    class _DB:
        def execute(self, statement, params):
            captured["sql"] = str(statement)
            captured["params"] = params
            return _Result()

    @contextmanager
    def _session():
        yield _DB()

    monkeypatch.setattr("src.app.services.demand_forecast.db_session", _session)
    forecaster = DemandForecaster(tenant_id="tenant-a")
    history = forecaster._read_history("SKU-1", lookback_days=30)

    assert captured["params"]["tenant"] == "tenant-a"
    assert captured["params"]["sku"] == "SKU-1"
    cutoff = datetime.fromisoformat(captured["params"]["cutoff"])
    assert cutoff.tzinfo == timezone.utc
    assert "marketing_event_fact" in captured["sql"]
    assert "event_type = 'purchase'" in captured["sql"]
    assert "status = 'active'" in captured["sql"]
    assert history == [
        {
            "date": "2026-07-20",
            "qty": 5.0,
            "trust": 0.88,
            "source": "canonical_purchase",
        },
        {
            "date": "2026-07-21",
            "qty": 4.0,
            "trust": 1.0,
            "source": "canonical_purchase",
        },
    ]


def test_inventory_agent_does_not_fall_back_to_unscoped_orders(monkeypatch):
    monkeypatch.setenv("INV_FORECAST_PIPELINE", "1")
    monkeypatch.setattr(
        "src.app.services.demand_forecast.DemandForecaster.forecast_sku",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("db down")),
    )
    agent = InventoryAgent(tenant_id="tenant-a")
    monkeypatch.setattr(
        agent,
        "_get_sales_series",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("unscoped fallback must not run")
        ),
    )

    result = agent._forecast_daily_demand("SKU-1")

    assert result["method"] == "canonical_unavailable"
    assert result["evidence_status"] == "degraded"
