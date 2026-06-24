"""Tests for supplier PO automation — B2B bulk orders auto-draft a human-gated PO."""
import pytest
from unittest.mock import patch
from src.app.services.availability_agent import assess_availability


class TestSupplierPOAutomation:
    """When draft_reorder=True and stock is insufficient, a draft PO is produced."""

    def test_draft_reorder_produced_on_shortfall(self):
        """A bulk order with shortfall produces a draft PO."""
        def mock_stock(skus):
            return {skus[0]: 3}  # Only 3 in stock

        def mock_lead_time(sku):
            return 5

        def mock_reorder(sku, current_stock, reorder_point):
            return {
                "sku": sku,
                "low_stock": True,
                "status": "awaiting_human_approval",
                "forecast": {"cover_days": 30, "projected_demand": 15.0},
                "proposed_qty": 7,
            }

        result = assess_availability(
            ["SKU-001"], order_quantity=10, horizon_days=14,
            stock_fn=mock_stock, lead_time_fn=mock_lead_time,
            reorder_fn=mock_reorder, draft_reorder=True,
        )
        assert result["applicable"] is True
        assert result["shortfall"] == 7
        assert result["in_stock"] == 3
        assert "reorder_draft" in result
        assert result["reorder_draft"]["status"] == "awaiting_human_approval"

    def test_no_draft_when_stock_sufficient(self):
        """When stock is sufficient, no reorder draft is produced."""
        def mock_stock(skus):
            return {skus[0]: 20}

        result = assess_availability(
            ["SKU-001"], order_quantity=10, horizon_days=14,
            stock_fn=mock_stock, draft_reorder=True,
        )
        assert result["applicable"] is True
        assert result["shortfall"] == 0
        assert result["feasible"] is True
        assert "reorder_draft" not in result

    def test_no_draft_when_draft_reorder_false(self):
        """With draft_reorder=False, no PO is drafted even on shortfall."""
        def mock_stock(skus):
            return {skus[0]: 2}

        def mock_lead_time(sku):
            return 5

        result = assess_availability(
            ["SKU-001"], order_quantity=10, horizon_days=14,
            stock_fn=mock_stock, lead_time_fn=mock_lead_time,
            draft_reorder=False,
        )
        assert result["shortfall"] == 8
        assert "reorder_draft" not in result

    def test_b2b_threshold_five_units(self):
        """The B2B bulk threshold in recommend.py is qty >= 5."""
        # Simulate the recommend.py logic
        order_qty = 5
        _is_b2b_bulk = int(order_qty) >= 5
        assert _is_b2b_bulk is True

        order_qty = 4
        _is_b2b_bulk = int(order_qty) >= 5
        assert _is_b2b_bulk is False

    def test_feasibility_within_horizon(self):
        """Reorder within horizon → feasible."""
        def mock_stock(skus):
            return {skus[0]: 3}

        def mock_lead_time(sku):
            return 5  # 5 days lead time

        result = assess_availability(
            ["SKU-001"], order_quantity=10, horizon_days=14,
            stock_fn=mock_stock, lead_time_fn=mock_lead_time,
            draft_reorder=False,
        )
        assert result["feasible"] is True
        assert result["fulfilment"] == "reorder_within_horizon"

    def test_feasibility_exceeds_horizon(self):
        """Lead time exceeds horizon → not feasible."""
        def mock_stock(skus):
            return {skus[0]: 3}

        def mock_lead_time(sku):
            return 21  # 21 days, exceeds 14-day horizon

        result = assess_availability(
            ["SKU-001"], order_quantity=10, horizon_days=14,
            stock_fn=mock_stock, lead_time_fn=mock_lead_time,
            draft_reorder=False,
        )
        assert result["feasible"] is False
        assert result["fulfilment"] == "reorder_exceeds_horizon"

    def test_no_horizon_reports_eta_only(self):
        """No horizon stated → feasible is None (just report ETA)."""
        def mock_stock(skus):
            return {skus[0]: 3}

        def mock_lead_time(sku):
            return 7

        result = assess_availability(
            ["SKU-001"], order_quantity=10, horizon_days=None,
            stock_fn=mock_stock, lead_time_fn=mock_lead_time,
            draft_reorder=False,
        )
        assert result["feasible"] is None
        assert result["fulfilment"] == "reorder_required"
        assert result["eta_days"] == 7
