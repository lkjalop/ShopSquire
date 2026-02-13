import json

from src.app.services.inventory_agent import InventoryAgent, ReorderRecommendation


def _read_flags() -> dict:
    with open("config/feature_flags.json", "r", encoding="utf-8") as f:
        return json.load(f)


def _write_flags(flags: dict) -> None:
    with open("config/feature_flags.json", "w", encoding="utf-8") as f:
        json.dump(flags, f, ensure_ascii=False, indent=2)


def test_inventory_execute_reorder_uses_configured_approval_threshold():
    flags = _read_flags()
    flags["INVENTORY_THRESHOLDS"] = {
        "reorder_cost_approval_usd": 100.0,
        "reorder_cost_high_severity_usd": 200.0,
        "data_readiness_min_score": 0.8,
        "data_readiness_required": False,
    }
    _write_flags(flags)

    agent = InventoryAgent()
    rec = ReorderRecommendation(
        sku="SKU-1",
        supplier_id="SUP-1",
        quantity=10,
        estimated_cost=150.0,
        lead_time_days=7,
        urgency="normal",
    )
    out = agent.execute_reorder(rec, approval=None)
    assert out.get("status") == "approval_required"
    assert out.get("threshold") == 100.0

