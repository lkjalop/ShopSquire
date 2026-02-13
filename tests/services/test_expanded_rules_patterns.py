"""Unit tests for fallback intent patterns in ExpandedRuleEngine."""

from src.app.services.expanded_rules import ExpandedRuleEngine


def test_stock_intent_pattern():
    engine = ExpandedRuleEngine()
    res = engine.evaluate("Is this item in stock?", {"memory": {}, "live": {}})
    assert isinstance(res, dict)
    assert res.get("handled") is True
    assert res.get("intent") in ("stock_check", "internal:stock_check") or res.get("rule_id")


def test_restock_alert_pattern():
    engine = ExpandedRuleEngine()
    res = engine.evaluate("Notify me when this is back in stock", {"memory": {}, "live": {}})
    assert res.get("handled") is True
    assert res.get("intent") in ("restock_alert", "internal:restock_alert") or res.get("rule_id")
