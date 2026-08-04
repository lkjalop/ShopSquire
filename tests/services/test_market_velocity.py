from src.app.services.market_analysis import detect_bulk_order_frequency, detect_velocity_dsi


def test_velocity_and_dsi_are_vertical_neutral():
    out = detect_velocity_dsi(
        [{"sku": "X", "quantity": 100}],
        [{"sku": "X", "available": 10}],
        window_days=30)["X"]
    assert out["velocity"] == 10
    assert out["dsi_days"] == 3
    assert out["dead_stock"] is False


def test_dead_stock_and_zero_stock_do_not_divide_by_zero():
    out = detect_velocity_dsi(
        [{"sku": "ZERO", "quantity": 4}],
        [{"sku": "DEAD", "available": 50}, {"sku": "ZERO", "available": 0}],
        window_days=30)
    assert out["DEAD"]["dead_stock"] is True and out["DEAD"]["dsi_days"] is None
    assert out["ZERO"]["stockout"] is True and out["ZERO"]["velocity"] is None


def test_bulk_frequency_counts_cases_not_versions():
    out = detect_bulk_order_frequency([
        {"case_id": "c1", "sku": "X", "quantity": 20},
        {"case_id": "c1", "sku": "X", "quantity": 20},
        {"case_id": "c2", "sku": "X", "quantity": 10},
        {"case_id": "c3", "sku": "Y", "quantity": 1},
    ], window_days=90)
    assert out["X"]["bulk_order_count"] == 2
    assert out["X"]["orders_per_30d"] == 0.667
    assert "Y" not in out
