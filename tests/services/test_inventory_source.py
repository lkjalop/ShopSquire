"""Inventory source adapter — canonical-over-legacy stock selection (the buyer-procurement-truth seam)."""
from __future__ import annotations

import pytest

from src.app.services import inventory_source as isrc


def _legacy(_skus):
    return {"GAM-0003": 14, "LAP-021": 14, "OTHER": 3}


def test_flag_off_returns_legacy_only(monkeypatch):
    monkeypatch.delenv("COMMERCE_CATALOG_ENABLED", raising=False)
    out = isrc.stock_levels(["GAM-0003", "LAP-021"], legacy_fn=_legacy,
                            canonical_fn=lambda s, t: {"LAP-021": 4})
    assert out["LAP-021"] == 14 and out["GAM-0003"] == 14  # canonical ignored when flag off


def test_flag_on_overlays_canonical_per_sku(monkeypatch):
    monkeypatch.setenv("COMMERCE_CATALOG_ENABLED", "1")
    out = isrc.stock_levels(["GAM-0003", "LAP-021"], legacy_fn=_legacy,
                            canonical_fn=lambda s, t: {"LAP-021": 4})  # catalog knows LAP-021 only
    assert out["LAP-021"] == 4       # canonical wins where present → real shortfall for a "10 units" order
    assert out["GAM-0003"] == 14     # catalog doesn't know it → legacy preserved (no false zero)


def test_overlay_is_pure():
    assert isrc._overlay({"a": 10, "b": 5}, {"a": 2}) == {"a": 2, "b": 5}
    assert isrc._overlay({"a": 10}, {}) == {"a": 10}


def test_empty_skus():
    assert isrc.stock_levels([]) == {}
