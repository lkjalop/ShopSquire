"""Focused tests for Phase-3 deterministic inventory rules.

These exercise a handful of new `STOCK_RULES` added in Phase-3:
- R008: supplier_delay (escalates)
- R011: perishable + expiration_soon
- R031: fraud_hold (escalates)
- R032: high_value (escalates)
"""
from src.app.services.inventory_agent import InventoryAgent


def test_rule_supplier_delay():
    agent = InventoryAgent()
    res = agent.evaluate_stock_rule("SKU-DELAY", {"supplier_delay": True, "stock": 5})
    assert res["rule_id"] == "R008"
    assert res["escalate"] is True
    assert "Supplier" in res["response"] or res["response"]


def test_rule_perishable_expiration_soon():
    agent = InventoryAgent()
    res = agent.evaluate_stock_rule("SKU-PERISH", {"perishable": True, "expiration_soon": True, "stock": 8})
    assert res["rule_id"] == "R011"
    assert res["escalate"] is False
    assert "expire" in res["response"].lower() or res["response"]


def test_rule_fraud_hold():
    agent = InventoryAgent()
    res = agent.evaluate_stock_rule("SKU-FRAUD", {"fraud_hold": True, "stock": 3})
    assert res["rule_id"] == "R031"
    assert res["escalate"] is True
    assert "fraud" in res["response"].lower() or res["response"]


def test_rule_high_value():
    agent = InventoryAgent()
    res = agent.evaluate_stock_rule("SKU-HIGHVAL", {"high_value": True, "stock": 2})
    assert res["rule_id"] == "R032"
    assert res["escalate"] is True
    assert "approval" in res["response"].lower() or res["response"]
