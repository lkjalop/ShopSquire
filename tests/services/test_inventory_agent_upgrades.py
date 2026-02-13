from contextlib import contextmanager

from src.app.services.inventory_agent import InventoryAgent, ReorderRecommendation, StockAlert


def test_execute_reorder_blocks_on_variance_without_approval(monkeypatch):
    monkeypatch.setenv("INVENTORY_DATA_READINESS_REQUIRED", "0")
    rec = ReorderRecommendation(
        sku="SKU-VAR",
        supplier_id="SUP-1",
        quantity=20,
        estimated_cost=120.0,
        lead_time_days=7,
        urgency="normal",
        requires_human_review_reason="forecast_variance_high",
    )
    out = InventoryAgent().execute_reorder(rec, approval=None)
    assert out.get("status") == "approval_required"
    assert out.get("reason") == "forecast_variance_high"


def test_generate_recommendation_includes_forecast_and_safety_stock(monkeypatch):
    agent = InventoryAgent()
    monkeypatch.setattr(
        agent,
        "_get_best_supplier",
        lambda sku: {"id": "SUP-1", "unit_cost": 5.0, "lead_time": 5, "moq": 10, "score": 0.8},
    )
    monkeypatch.setattr(
        agent,
        "_forecast_daily_demand",
        lambda sku: {"method": "ewma", "daily_demand": 3.0, "std_daily": 1.2, "variance": 1.44, "high_variance": False, "cv": 0.4},
    )
    monkeypatch.setattr(
        agent,
        "_calculate_eoq",
        lambda sku, supplier, forecast: {"qty": 18, "safety_stock": 4, "method": "ewma", "annual_demand": 1095.0},
    )
    alerts = [StockAlert(sku="SKU-1", warehouse="default", current_stock=1, reorder_point=10, alert_type="low_stock")]
    recs = agent.generate_reorder_recommendations(alerts)
    assert len(recs) == 1
    rec = recs[0]
    assert rec.quantity == 18
    assert rec.forecast_daily_demand == 3.0
    assert rec.forecast_variance == 1.44
    assert rec.safety_stock == 4


def test_rebalance_suggestion_for_large_cover_gap(monkeypatch):
    rows = [("SKU-1", "w-low", 2), ("SKU-1", "w-high", 40)]

    class _R:
        def fetchall(self):
            return rows

    class _DB:
        def execute(self, *args, **kwargs):
            return _R()

    @contextmanager
    def _fake_db_session():
        yield _DB()

    monkeypatch.setattr("src.app.services.inventory_agent.db_session", _fake_db_session)
    agent = InventoryAgent()
    monkeypatch.setattr(agent, "_forecast_daily_demand", lambda sku: {"daily_demand": 2.0})
    out = agent.suggest_rebalancing_transfers(max_suggestions=5, min_days_cover_gap=5.0)
    assert len(out) == 1
    assert out[0]["from_warehouse"] == "w-high"
    assert out[0]["to_warehouse"] == "w-low"
    assert out[0]["quantity"] >= 1


def test_anomaly_calibration_returns_severity_band():
    agent = InventoryAgent()
    low = agent._calibrate_inventory_anomaly(-3.0)
    high = agent._calibrate_inventory_anomaly(5.0)
    assert low["severity"] in ("low", "medium")
    assert high["severity"] in ("high", "critical")


def test_monitor_stock_levels_falls_back_when_reorder_point_column_missing(monkeypatch):
    class _Rows:
        def __init__(self, data):
            self._data = data

        def fetchall(self):
            return self._data

    class _DB:
        def __init__(self):
            self.calls = 0

        def execute(self, stmt, params=None):
            self.calls += 1
            sql = str(stmt)
            if "COALESCE(p.reorder_point" in sql:
                raise RuntimeError("column products.reorder_point does not exist")
            return _Rows([("SKU-FB", "default", 1, 3, "2026-02-10T00:00:00Z")])

    @contextmanager
    def _fake_db_session():
        yield _DB()

    monkeypatch.setattr("src.app.services.inventory_agent.db_session", _fake_db_session)
    monkeypatch.setenv("INVENTORY_DEFAULT_REORDER_POINT", "3")

    alerts = InventoryAgent().monitor_stock_levels()
    assert alerts
    assert alerts[0].sku == "SKU-FB"
    assert alerts[0].reorder_point == 3
