"""Tests for InventoryAgent deterministic stock rules."""

from src.app.services.inventory_agent import InventoryAgent


def test_evaluate_stock_rule_in_stock():
    agent = InventoryAgent()
    res = agent.evaluate_stock_rule("SKU123", {"stock": 25, "lead_time": 2})
    assert res.get("rule_id") == "R001"
    assert "In stock" in res.get("response")


def test_evaluate_stock_rule_low_stock():
    agent = InventoryAgent()
    res = agent.evaluate_stock_rule("SKU123", {"stock": 3})
    assert res.get("rule_id") == "R002"
    assert "Limited stock" in res.get("response")


def test_evaluate_stock_rule_out_of_stock_reorder():
    agent = InventoryAgent()
    res = agent.evaluate_stock_rule("SKU123", {"stock": 0, "reorder_active": True, "eta_days": 5})
    assert res.get("rule_id") == "R003"
    assert "Temporarily out of stock" in res.get("response")
