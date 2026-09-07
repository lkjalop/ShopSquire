from src.app.services.order_economics import OrderEconomics


def test_stock_projection_uses_canonical_location_snapshot_not_network_total():
    from src.app.services.order_economics import project_stock_economics
    result = project_stock_economics({"quantity": 25, "budget_shortfall_cents": 0}, {
        "sku": "P1", "requested_qty": 25, "in_stock": 49,
        "inventory_snapshot": {"requested_quantity": 25, "local_atp": 4,
            "transferable": 21, "unconfirmed_shortfall": 0, "status": "degraded",
            "conservation_ok": True, "freshness_status": "unknown"},
    })
    assert result["local_stock"] == 4
    assert result["network_transferable"] == 21
    assert result["supplier_shortfall"] == 0
    assert result["stock_evidence_status"] == "degraded"
    assert result["budget_shortfall_cents"] == 0


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
