"""Availability_Agent: 'can we fulfil N units by day D?' from stock + lead-time, with a HUMAN-GATED
reorder draft for the shortfall. Pure logic with injected deps — no DB. Governance: never sends."""
from __future__ import annotations

from src.app.services.availability_agent import assess_availability


def test_in_stock_fully_covers_order():
    r = assess_availability(["A"], 5, 28, stock_fn=lambda s: {"A": 10}, lead_time_fn=lambda x: 7)
    assert r["feasible"] is True and r["fulfilment"] == "in_stock"
    assert r["shortfall"] == 0 and r["eta_days"] == 0


def test_shortfall_within_horizon_is_feasible():
    r = assess_availability(["A"], 10, 28, stock_fn=lambda s: {"A": 4}, lead_time_fn=lambda x: 14)
    assert r["shortfall"] == 6 and r["lead_time_days"] == 14
    assert r["feasible"] is True and r["fulfilment"] == "reorder_within_horizon"


def test_shortfall_exceeds_horizon_not_feasible():
    r = assess_availability(["A"], 10, 14, stock_fn=lambda s: {"A": 0}, lead_time_fn=lambda x: 28)
    assert r["shortfall"] == 10 and r["feasible"] is False
    assert r["fulfilment"] == "reorder_exceeds_horizon"


def test_no_horizon_reports_eta_without_judging():
    r = assess_availability(["A"], 10, None, stock_fn=lambda s: {"A": 2}, lead_time_fn=lambda x: 10)
    assert r["feasible"] is None and r["eta_days"] == 10
    assert r["fulfilment"] == "reorder_required"


def test_draft_reorder_is_human_gated_and_uses_shortfall_context():
    captured = {}

    def fake_reorder(sku, current_stock, reorder_point):
        captured.update(sku=sku, cs=current_stock, rp=reorder_point)
        return {"status": "awaiting_human_approval", "low_stock": True}

    r = assess_availability(
        ["A"], 10, 28, stock_fn=lambda s: {"A": 4}, lead_time_fn=lambda x: 14,
        reorder_fn=fake_reorder, draft_reorder=True,
    )
    assert r["reorder_draft"]["status"] == "awaiting_human_approval"
    assert captured == {"sku": "A", "cs": 4, "rp": 10}  # current stock + requested qty as reorder point


def test_not_applicable_without_skus_or_quantity():
    assert assess_availability([], 10).get("applicable") is False
    assert assess_availability(["A"], 0).get("applicable") is False


# ── Step 4: the plain availability line (what reaches the assistant message) ──
from src.app.services.availability_agent import availability_summary_line  # noqa: E402
from src.app.services.query_decomposer import decompose  # noqa: E402


def test_summary_line_in_stock():
    v = assess_availability(["A"], 5, 28, stock_fn=lambda s: {"A": 10}, lead_time_fn=lambda x: 7)
    assert availability_summary_line(v) == "On availability: all 5 are in stock now."


def test_summary_line_within_horizon_is_feasible():
    v = assess_availability(["A"], 10, 28, stock_fn=lambda s: {"A": 4}, lead_time_fn=lambda x: 14)
    line = availability_summary_line(v)
    assert "4 in stock now" in line and "other 6" in line and "~14 days" in line and "feasible" in line


def test_summary_line_exceeds_horizon_offers_draft():
    v = assess_availability(["A"], 10, 14, stock_fn=lambda s: {"A": 0}, lead_time_fn=lambda x: 28)
    line = availability_summary_line(v)
    assert "beyond your 14-day window" in line and "draft a supplier reorder" in line


def test_summary_line_empty_when_not_applicable():
    assert availability_summary_line({"applicable": False}) == ""


def test_full_chain_decompose_to_line():
    # End-to-end (no recommend route): the decomposer's qty+horizon feed the agent + line.
    plan = decompose("10 business laptops, budget 1600, can you deliver in 4 weeks?")
    assert plan.quantity == 10 and plan.availability_horizon_days == 28
    v = assess_availability(["LAP-1"], plan.quantity, plan.availability_horizon_days,
                            stock_fn=lambda s: {"LAP-1": 4}, lead_time_fn=lambda x: 14)
    line = availability_summary_line(v)
    assert "4 in stock now" in line and "10 within 28 days is feasible" in line
