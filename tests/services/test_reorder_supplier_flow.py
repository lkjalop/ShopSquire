"""Demand -> supplier reorder flow (bounded, draft-first, human-approval-required, never sends)."""
from __future__ import annotations

from types import SimpleNamespace

from src.app.services.reorder_supplier_flow import plan_reorder_with_supplier_draft

# 30 days of ~2 units/day demand
_FC = SimpleNamespace(daily=[{"mean": 2.0} for _ in range(30)])


def _forecast(sku, cover_days):
    return _FC


def _draft(*, kind, supplier_name, supplier_email, item, details, templates=None):
    return {"kind": kind, "supplier_name": supplier_name, "item": item, "details": details}


def test_no_reorder_when_stock_sufficient():
    out = plan_reorder_with_supplier_draft(
        sku="GAM-1", current_stock=50, reorder_point=10, forecast_fn=_forecast, draft_fn=_draft)
    assert out["low_stock"] is False and out["status"] == "ok_no_reorder"
    assert "draft" not in out  # nothing drafted


def test_low_stock_forecasts_proposes_and_drafts_awaiting_approval():
    out = plan_reorder_with_supplier_draft(
        sku="GAM-1", current_stock=5, reorder_point=10, supplier_name="Acme",
        supplier_email="x@acme.com", cover_days=30, forecast_fn=_forecast, draft_fn=_draft)
    assert out["low_stock"] is True
    assert out["forecast"]["projected_demand"] == 60.0   # 30 * 2.0
    assert out["proposed_qty"] == 55                       # ceil(60) - 5 on hand
    assert out["status"] == "awaiting_human_approval"      # human approval REQUIRED
    assert out["draft"]["kind"] == "reorder" and "GAM-1" in out["draft"]["item"]


def test_proposed_qty_floored_at_zero():
    out = plan_reorder_with_supplier_draft(
        sku="GAM-1", current_stock=10, reorder_point=10,  # low (==), but stock covers demand
        cover_days=30, forecast_fn=lambda s, d: SimpleNamespace(daily=[{"mean": 0.1}] * 30), draft_fn=_draft)
    assert out["low_stock"] is True and out["proposed_qty"] == 0  # ceil(3) - 10 -> max(0, -7)


def test_flow_never_sends_and_survives_forecast_failure():
    def _boom(sku, cover_days):
        raise RuntimeError("forecast down")
    out = plan_reorder_with_supplier_draft(
        sku="GAM-1", current_stock=1, reorder_point=10, forecast_fn=_boom, draft_fn=_draft)
    # forecast failed -> projected 0 -> proposed 0, but a draft is still produced for human review
    assert out["status"] == "awaiting_human_approval" and out["proposed_qty"] == 0
    assert "draft" in out  # still drafted; nothing sent (no mailer in this flow)
