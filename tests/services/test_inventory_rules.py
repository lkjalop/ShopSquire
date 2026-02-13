import pytest

from src.app.services.inventory_rules import evaluate_stock_rules


class DummyRecorder:
    def __init__(self):
        self.events = []

    def __call__(self, *args, **kwargs):
        self.events.append((args, kwargs))


def test_in_stock_triggers_in_stock_and_logs(monkeypatch):
    recorder_event = DummyRecorder()
    recorder_decision = DummyRecorder()
    monkeypatch.setattr("src.app.services.inventory_rules.log_trace_event", recorder_event)
    monkeypatch.setattr("src.app.services.inventory_rules.log_decision", recorder_decision)

    ctx = {"sku": "sku-1", "stock": 25, "reserved": 0, "product": {"price": 100}}
    out = evaluate_stock_rules(ctx)

    assert "trace_id" in out
    dec = out["decision"]
    assert dec["action"] in ("in_stock", None) or dec["action"] == "in_stock"
    # ensure some rules triggered (rule 1 should trigger)
    assert 1 in dec["triggered_rules"]
    # log_trace_event and log_decision should have been called at least once
    assert len(recorder_event.events) >= 1
    assert len(recorder_decision.events) == 1


def test_out_of_stock_reorder(monkeypatch):
    recorder_event = DummyRecorder()
    recorder_decision = DummyRecorder()
    monkeypatch.setattr("src.app.services.inventory_rules.log_trace_event", recorder_event)
    monkeypatch.setattr("src.app.services.inventory_rules.log_decision", recorder_decision)

    ctx = {"sku": "sku-2", "stock": 0, "reorder_in_progress": True}
    out = evaluate_stock_rules(ctx)
    dec = out["decision"]
    # rule 3 should have triggered for reorder
    assert 3 in dec["triggered_rules"]
    assert dec["action"] in ("back_soon", "unavailable", None)


def test_high_fraud_combo_requires_verification(monkeypatch):
    recorder_event = DummyRecorder()
    recorder_decision = DummyRecorder()
    monkeypatch.setattr("src.app.services.inventory_rules.log_trace_event", recorder_event)
    monkeypatch.setattr("src.app.services.inventory_rules.log_decision", recorder_decision)

    ctx = {"sku": "sku-3", "stock": 5, "customer": {"vip": False}, "high_fraud_combo": True}
    out = evaluate_stock_rules(ctx)
    dec = out["decision"]
    assert 60 in dec["triggered_rules"]
    assert dec["action"] == "require_verification"
