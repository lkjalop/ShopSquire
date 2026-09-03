from src.app.services.order_economics import OrderEconomics


def test_order_economics_is_one_cents_exact_contract():
    outcome = OrderEconomics.from_assessment({
        "quantity": 10,
        "total_cents": 3_000_000,
        "per_unit_cents": 300_000,
        "floor_cents": 119_900,
        "needed_cents": 1_199_000,
        "units_affordable": 25,
        "verdict": "fits",
        "tradeoffs": [],
    }, budget_scope="total", quantity_unit="laptop")
    payload = outcome.to_dict()
    assert payload["total_budget_cents"] == 3_000_000
    assert payload["per_unit_cap_cents"] == 300_000
    assert payload["required_total_cents"] == 1_199_000
    assert payload["budget_shortfall_cents"] == 0
    assert "total" not in payload
    assert "floor_cents" not in payload
