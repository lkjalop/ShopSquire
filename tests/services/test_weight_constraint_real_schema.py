"""Roadmap #1 — semantic & constraint truth: weight extraction + honest "no exact match".

Uses the REAL seeded product schema (scripts/seed_gaming_laptops.py shape: structured specs with
weight_kg) — not a simplified candidate. Closes the Tier-0 residual where the weight constraint
couldn't filter because the extractor didn't read weight. Core stays agnostic (it reads the generic
"weight_kg" key); the electronics adapter extractor populates it.
"""
from __future__ import annotations

from src.app.routers.recommend import _apply_query_plan_filters
from src.app.services.recommend_utils import _extract_candidate_numeric_specs


# Mirrors the seed_gaming_laptops.py product schema (structured specs, weight_kg present).
def _seed_like(sku, name, weight_kg, ram=16, refresh=144):
    return {"id": sku, "sku": sku, "name": name, "price_cents": 129900, "currency": "USD",
            "specs": {"ram_gb": ram, "storage_gb": 1024, "refresh_hz": refresh,
                      "weight_kg": weight_kg, "gpu": "RTX 4060"}}


class _Plan:
    def __init__(self, hc):
        self.hard_constraints = hc
        self.category = "laptop"
        self.intent = "product_search"


def test_weight_extracted_from_real_schema():
    specs = _extract_candidate_numeric_specs(_seed_like("GAM-1", "MSI Katana 15", 2.9))
    assert specs.get("weight_kg") == 2.9


def test_weight_extracted_from_lbs_in_name():
    specs = _extract_candidate_numeric_specs(
        {"name": "UltraLight 5.5 lbs notebook", "specs": {}})
    assert specs.get("weight_kg") is not None and 2.4 <= specs["weight_kg"] <= 2.6  # 5.5 lb ≈ 2.5kg


def test_all_overweight_catalog_reports_no_exact_match():
    # Every seeded gaming laptop is 2.1-2.9kg; "under 2kg" must NOT silently show violators.
    catalog = [_seed_like("A", "MSI Katana 15", 2.9), _seed_like("B", "HP Victus 16", 2.4),
               _seed_like("C", "ASUS ROG Strix", 2.6)]
    results, dropped = _apply_query_plan_filters(catalog, _Plan({"weight_kg_max": 2.0}))
    assert results, "never blank"
    assert dropped.get("exact_match") is False
    assert "weight" in (dropped.get("violated_constraints") or [])


def test_a_light_option_is_an_exact_match():
    catalog = [_seed_like("A", "MSI Katana 15", 2.9), _seed_like("C", "LG Gram 17", 1.35)]
    results, dropped = _apply_query_plan_filters(catalog, _Plan({"weight_kg_max": 2.0}))
    assert [r["sku"] for r in results] == ["C"]
    assert dropped.get("exact_match") is True
