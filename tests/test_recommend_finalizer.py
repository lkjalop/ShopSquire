"""Contract tests for recommend_response_finalizer.

Verifies the invariants that the finalizer guarantees before any answer
generation or payload assembly takes place.
"""
from __future__ import annotations

import pytest
from unittest.mock import patch
from src.app.services.recommend_response_finalizer import finalize_recommendation_response


def _make_result(sku: str, name: str, price: int = 100000, stock: int = 10, factors=None) -> dict:
    return {
        "sku": sku,
        "name": name,
        "price_cents": price,
        "stock": stock,
        "factors": factors or {"positive": ["+in_stock", "+within_budget"], "negative": []},
    }


MOCK_STOCK = {"SKU-A": 5, "SKU-B": 0, "SKU-C": 12, "SKU-DUP": 3}


@pytest.fixture(autouse=True)
def _mock_stock(monkeypatch):
    import src.app.services.inventory_query_service as _iq
    monkeypatch.setattr(_iq, "batch_stock_levels", lambda skus: {s: MOCK_STOCK.get(s, 10) for s in skus})


class TestContractInvariants:
    def test_empty_input_returns_empty(self):
        r = finalize_recommendation_response([], {})
        assert r.results == []
        assert r.contract_valid

    def test_all_results_have_stock_level(self):
        items = [_make_result("SKU-A", "Laptop A"), _make_result("SKU-C", "Laptop C")]
        r = finalize_recommendation_response(items, {})
        for item in r.results:
            assert item["stock_level"] is not None, f"stock_level missing on {item['sku']}"

    def test_all_results_have_why(self):
        items = [_make_result("SKU-A", "Laptop A")]
        r = finalize_recommendation_response(items, {})
        for item in r.results:
            assert isinstance(item.get("why"), list) and item["why"], f"why missing on {item['sku']}"

    def test_oos_items_sorted_to_end(self):
        items = [
            _make_result("SKU-B", "OOS Laptop", stock=0),   # out-of-stock
            _make_result("SKU-A", "Good Laptop", stock=5),
            _make_result("SKU-C", "Great Laptop", stock=12),
        ]
        r = finalize_recommendation_response(items, {})
        in_stock = [i for i in r.results if i["stock_status"] != "out_of_stock"]
        out_of_stock = [i for i in r.results if i["stock_status"] == "out_of_stock"]
        assert len(in_stock) == 2
        assert len(out_of_stock) == 1
        # OOS must be last
        last_sku = r.results[-1]["sku"]
        assert last_sku == "SKU-B", f"Expected OOS item last, got {last_sku}"

    def test_oos_removed_when_filter_opted(self):
        items = [
            _make_result("SKU-B", "OOS Laptop", stock=0),
            _make_result("SKU-A", "In-stock Laptop", stock=5),
        ]
        r = finalize_recommendation_response(items, {}, stock_filter_opted=True)
        assert all(i["stock_status"] != "out_of_stock" for i in r.results)
        assert len(r.oos_removed) == 1
        assert r.oos_removed[0]["sku"] == "SKU-B"

    def test_deduplication_keeps_first(self):
        items = [
            _make_result("SKU-A", "Laptop First"),
            _make_result("SKU-A", "Laptop Duplicate"),
            _make_result("SKU-C", "Laptop Unique"),
        ]
        r = finalize_recommendation_response(items, {})
        skus = [i["sku"] for i in r.results]
        assert skus.count("SKU-A") == 1
        assert r.results[0]["name"] == "Laptop First"

    def test_cart_eligible_matches_stock(self):
        items = [
            _make_result("SKU-A", "In Stock", stock=5),
            _make_result("SKU-B", "OOS", stock=0),
        ]
        r = finalize_recommendation_response(items, {})
        by_sku = {i["sku"]: i for i in r.results}
        assert by_sku["SKU-A"]["cart_eligible"] is True
        assert by_sku["SKU-B"]["cart_eligible"] is False

    def test_contract_valid_for_well_formed_results(self):
        items = [_make_result("SKU-A", "Good Laptop")]
        r = finalize_recommendation_response(items, {})
        assert r.contract_valid, f"Unexpected violations: {r.contract_violations}"

    def test_contract_invalid_reports_violations(self):
        items = [{"name": "No SKU Laptop", "price_cents": 100000, "stock": 5, "factors": {}}]
        r = finalize_recommendation_response(items, {})
        assert not r.contract_valid
        assert any("missing sku" in v for v in r.contract_violations)

    def test_very_low_stock_label(self):
        items = [_make_result("SKU-DUP", "Low Stock Laptop", stock=3)]
        r = finalize_recommendation_response(items, {})
        item = r.results[0]
        assert item["stock_status"] == "very_low_stock"
        assert "Only" in item.get("stock_urgency", "")

    def test_why_fallback_when_factors_empty(self):
        items = [{"sku": "SKU-A", "name": "Laptop", "price_cents": 100000, "stock": 5}]
        r = finalize_recommendation_response(items, {})
        assert r.results[0]["why"] == ["matched your query"]

    def test_non_dict_entries_skipped(self):
        items = [None, _make_result("SKU-A", "Valid"), "bad_entry", 42]
        r = finalize_recommendation_response(items, {})
        assert len(r.results) == 1
        assert r.results[0]["sku"] == "SKU-A"

    def test_assistant_top_names_match_results(self):
        """Proxy test: after finalization, results[0] is the in-stock item."""
        items = [
            _make_result("SKU-B", "OOS First", stock=0),
            _make_result("SKU-A", "In-stock Second", stock=5),
        ]
        r = finalize_recommendation_response(items, {})
        # If LLM described results[0] as the top pick, it should be the in-stock item
        assert r.results[0]["sku"] == "SKU-A"
