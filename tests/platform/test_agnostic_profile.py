"""Agnostic proof harness — the core/adapter line must hold across verticals.

This test GROWS as flavour slots are excised from the core into StoreProfile reads.
Today brand_price_floors + nqe_brand_detect are profile-backed; this asserts a pharmacy
profile serves DIFFERENT flavour than electronics through the SAME loader — i.e. the core
mechanism doesn't bake in laptop assumptions. As R2/R3 excise use-case/spec patterns, add
assertions here that a pharmacy query gets pharmacy slots, not laptop GPU/refresh specs.
"""
from __future__ import annotations

from src.app.platform.store_profile import get_store_profile, brand_price_floors, profile_slot, reset_cache


def setup_function(_):
    reset_cache()  # never let one vertical's profile leak into the next assertion


def test_two_verticals_load_through_one_loader():
    assert get_store_profile("electronics").get("id") == "electronics"
    assert get_store_profile("pharmacy").get("id") == "pharmacy"


def test_brand_detection_differs_by_vertical():
    elec = set(profile_slot("nqe_brand_detect", profile_id="electronics", default=[]))
    pharm = set(profile_slot("nqe_brand_detect", profile_id="pharmacy", default=[]))
    assert "asus" in elec and "asus" not in pharm        # no laptop brand leaks into pharmacy
    assert "panadol" in pharm and "panadol" not in elec  # no pharmacy brand leaks into laptops
    assert not (elec & pharm)                            # disjoint vocabularies


def test_price_floors_differ_by_vertical():
    elec = brand_price_floors("electronics")
    pharm = brand_price_floors("pharmacy")
    assert elec.get("asus") == 400                       # laptop economics
    assert pharm.get("blackmores") == 10                 # pharmacy economics
    assert "asus" not in pharm                            # laptop floors don't apply to pharmacy


def test_pharmacy_carries_regulatory_policy_flags():
    # The moat: pharmacy needs policy the recommender must respect (schedule/age gating).
    flags = profile_slot("policy_flags", profile_id="pharmacy", default={})
    assert flags.get("schedule_gated") is True
    assert "medicine" in (flags.get("age_restricted_types") or [])


def test_primary_types_are_vertical_specific():
    assert "laptop" in profile_slot("primary_types", profile_id="electronics", default=[])
    assert "laptop" not in profile_slot("primary_types", profile_id="pharmacy", default=[])
    assert "medicine" in profile_slot("primary_types", profile_id="pharmacy", default=[])
