from src.app.services.seasonal_market_scenario import build_back_to_school_scenario


def test_scenario_is_deterministic_isolated_and_spans_january_to_march():
    products = [
        {"sku": "A", "price_cents": 100000, "currency": "AUD"},
        {"sku": "B", "price_cents": 200000, "currency": "AUD"},
    ]
    first = build_back_to_school_scenario(products, tenant_id="synthetic-test", max_products=2)
    second = build_back_to_school_scenario(products, tenant_id="synthetic-test", max_products=2)
    assert first == second
    assert len(first["atp"]) == 26
    months = {row["occurred_at"][5:7] for row in first["marketing"]}
    assert months == {"01", "02", "03"}
    assert all(row["tenant_id"] == "synthetic-test" for row in first["marketing"] + first["atp"])
    assert all(row["source_system"] == "synthetic_scenario" for row in first["marketing"] + first["atp"])


def test_scenario_refuses_production_tenant():
    try:
        build_back_to_school_scenario([], tenant_id="default")
    except ValueError as exc:
        assert "synthetic" in str(exc)
    else:
        raise AssertionError("production tenant must be rejected")
