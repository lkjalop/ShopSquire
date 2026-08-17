"""Inventory source adapter — canonical-over-legacy stock selection (the buyer-procurement-truth seam)."""
from __future__ import annotations

from src.app.services import inventory_source as isrc


def _legacy(_skus):
    return {"GAM-0003": 14, "LAP-021": 14, "OTHER": 3}


def test_flag_off_returns_legacy_only(monkeypatch):
    # control the gate directly (it now reads env OR feature_flags.json — don't depend on ambient config)
    monkeypatch.setattr("src.app.services.commerce_catalog.catalog_enabled", lambda: False)
    out = isrc.stock_levels(["GAM-0003", "LAP-021"], legacy_fn=_legacy,
                            canonical_fn=lambda s, t: {"LAP-021": 4})
    assert out["LAP-021"] == 14 and out["GAM-0003"] == 14  # canonical ignored when flag off
    assert out.tool_selection_receipt["capability"] == "inventory_availability"
    assert out.tool_selection_receipt["outcome"] == "selected"
    assert out.tool_selection_receipt["commercial_authority_granted"] is False


def test_flag_on_overlays_canonical_per_sku(monkeypatch):
    monkeypatch.setattr("src.app.services.commerce_catalog.catalog_enabled", lambda: True)
    out = isrc.stock_levels(["GAM-0003", "LAP-021"], legacy_fn=_legacy,
                            canonical_fn=lambda s, t: {"LAP-021": 4})  # catalog knows LAP-021 only
    assert out["LAP-021"] == 4       # canonical wins where present → real shortfall for a "10 units" order
    assert out["GAM-0003"] == 14     # catalog doesn't know it → legacy preserved (no false zero)


def test_overlay_is_pure():
    assert isrc._overlay({"a": 10, "b": 5}, {"a": 2}) == {"a": 2, "b": 5}
    assert isrc._overlay({"a": 10}, {}) == {"a": 10}


def test_empty_skus():
    assert isrc.stock_levels([]) == {}


def test_inventory_read_exposes_provider_neutral_selection_receipt(monkeypatch):
    monkeypatch.setattr("src.app.services.commerce_catalog.catalog_enabled", lambda: False)
    result = isrc.stock_levels_with_receipt(
        ["SKU-A"], legacy_fn=lambda _skus: {"SKU-A": 4},
    )
    assert result["levels"] == {"SKU-A": 4}
    assert result["tool_selection_receipt"]["capability"] == "inventory_availability"
    assert result["tool_selection_receipt"]["commercial_authority_granted"] is False
