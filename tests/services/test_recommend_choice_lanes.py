"""Backend recommendation choice-lanes: candidates are grouped into profile-defined lanes on evidence,
a work query never surfaces a gaming chassis as a PRIMARY pick, and the core stays vertical-blind
(lane definitions come from the profile; an empty profile → [] so the caller falls back to its heuristic).
"""
from __future__ import annotations

import os

os.environ.setdefault("STORE_PROFILE_ID", "electronics")

from src.app.platform.store_profile import profile_slot  # noqa: E402
from src.app.services.recommend_choice_lanes import assign_device_lanes, fleet_advisory  # noqa: E402

_FAKE_LANES = [
    {"key": "biz", "title": "Business", "markers": ["thinkpad", "latitude"], "exclusions": ["gaming"],
     "explain": "biz", "metrics": ["warranty"], "priority": 10, "primary_for": ["office"]},
    {"key": "mac", "title": "Mac", "markers": ["macbook"], "exclusions": [], "priority": 20, "primary_for": ["office"]},
    {"key": "game", "title": "Gaming", "markers": ["rtx", "gaming"], "exclusions": [], "priority": 90,
     "non_primary": True, "primary_for": ["gaming"]},
]


def _fake_profile(key, profile_id=None, default=None):
    return _FAKE_LANES if key == "recommendation_lanes" else default


def test_empty_profile_returns_no_lanes():
    assert assign_device_lanes([{"sku": "A", "name": "Lenovo ThinkPad"}],
                               profile_fn=lambda k, profile_id=None, default=None: default) == []


def test_no_products_returns_no_lanes():
    assert assign_device_lanes([], profile_fn=_fake_profile) == []


def test_candidates_group_by_marker_into_lanes():
    prods = [
        {"sku": "TP", "name": "Lenovo ThinkPad T14", "specs": {}},
        {"sku": "MB", "name": "Apple MacBook Air", "specs": {}},
        {"sku": "KT", "name": "MSI Katana Gaming Laptop", "specs": {"gpu": "GeForce RTX 4070"}},
    ]
    lanes = {l["key"]: l for l in assign_device_lanes(prods, profile_fn=_fake_profile, use_case="office")}
    assert lanes["biz"]["skus"] == ["TP"]
    assert lanes["mac"]["skus"] == ["MB"]
    assert lanes["game"]["skus"] == ["KT"]


def test_exclusion_keeps_gaming_out_of_business_lane():
    # a "ThinkPad gaming" oddity must NOT land in the business lane (exclusion wins over marker)
    prods = [{"sku": "X", "name": "Lenovo ThinkPad gaming edition", "specs": {}}]
    lanes = {l["key"]: l for l in assign_device_lanes(prods, profile_fn=_fake_profile, use_case="office")}
    assert "biz" not in lanes  # excluded from business
    # it matches the gaming lane instead (rtx/gaming marker) — or 'other' if neither; here 'gaming'
    assert lanes.get("game", {}).get("skus") == ["X"]


def test_work_query_marks_business_primary_and_gaming_non_primary():
    prods = [
        {"sku": "TP", "name": "Lenovo ThinkPad T14", "specs": {}},
        {"sku": "KT", "name": "MSI Katana Gaming Laptop", "specs": {"gpu": "GeForce RTX 4070"}},
    ]
    lanes = {l["key"]: l for l in assign_device_lanes(prods, profile_fn=_fake_profile, use_case="office")}
    assert lanes["biz"]["primary"] is True
    assert lanes["game"]["primary"] is False and lanes["game"]["non_primary"] is True
    # primary lanes are ordered before non-primary
    order = [l["key"] for l in assign_device_lanes(prods, profile_fn=_fake_profile, use_case="office")]
    assert order.index("biz") < order.index("game")


def test_uncategorized_products_fall_into_other_lane():
    prods = [{"sku": "Z", "name": "Generic NoName Laptop", "specs": {}}]
    lanes = {l["key"]: l for l in assign_device_lanes(prods, profile_fn=_fake_profile, use_case="office")}
    assert lanes["other"]["skus"] == ["Z"] and lanes["other"]["non_primary"] is True


# ── against the REAL electronics profile ────────────────────────────────────────
def test_real_electronics_profile_work_query_demarcates_lanes():
    prods = [
        {"sku": "TP1", "name": "Lenovo ThinkPad T14 (vPro)", "specs": {"use_case": "business"}},
        {"sku": "MB1", "name": "Apple MacBook Air 13 (Apple M3)", "specs": {}},
        {"sku": "SF1", "name": "Microsoft Surface Laptop 6", "specs": {}},
        {"sku": "CB1", "name": "Acer Chromebook Spin 514", "specs": {}},
        {"sku": "IN1", "name": "Dell Inspiron 15", "specs": {"use_case": "value"}},
        {"sku": "KT1", "name": "MSI Katana 15 Gaming Laptop", "specs": {"gaming_style": True, "use_case": "gaming"}},
    ]
    lanes = assign_device_lanes(prods, profile_fn=profile_slot, use_case="office")
    by_key = {l["key"]: l for l in lanes}
    assert by_key["windows_business"]["skus"] == ["TP1"] and by_key["windows_business"]["primary"] is True
    assert by_key["apple_macbook"]["skus"] == ["MB1"]
    assert by_key["microsoft_surface"]["skus"] == ["SF1"]
    assert by_key["chromebook"]["skus"] == ["CB1"]
    assert by_key["budget_consumer"]["skus"] == ["IN1"]
    # the gaming SKU is isolated to the non-primary lane — never a primary office pick
    g = by_key["gaming_chassis"]
    assert g["skus"] == ["KT1"] and g["primary"] is False and g["non_primary"] is True
    primary_skus = [s for l in lanes if l["primary"] for s in l["skus"]]
    assert "KT1" not in primary_skus


# ── procurement-truth: fleet_advisory ───────────────────────────────────────────
def test_fleet_advisory_advises_procurement_when_only_gaming_for_work():
    # a work query whose only in-budget options are gaming → advise sourcing, not selling gaming
    prods = [{"sku": "KT1", "name": "MSI Katana 15 Gaming Laptop", "specs": {"gaming_style": True, "use_case": "gaming"}}]
    lanes = assign_device_lanes(prods, profile_fn=profile_slot, use_case="office")
    adv = fleet_advisory(lanes, use_case="office")
    assert adv and adv["coverage"] == "none" and adv["suggest_procurement"] is True
    assert "gaming_chassis" in adv["non_primary_lanes"]


def test_fleet_advisory_partial_when_business_and_gaming_present():
    prods = [
        {"sku": "TP1", "name": "Lenovo ThinkPad T14 (vPro)", "specs": {"use_case": "business"}},
        {"sku": "KT1", "name": "MSI Katana 15 Gaming Laptop", "specs": {"gaming_style": True}},
    ]
    lanes = assign_device_lanes(prods, profile_fn=profile_slot, use_case="office")
    adv = fleet_advisory(lanes, use_case="office")
    assert adv and adv["coverage"] == "partial" and adv["suggest_procurement"] is False


def test_fleet_advisory_none_when_clean_fleet_or_no_use_case():
    prods = [{"sku": "TP1", "name": "Lenovo ThinkPad T14", "specs": {"use_case": "business"}}]
    lanes = assign_device_lanes(prods, profile_fn=profile_slot, use_case="office")
    assert fleet_advisory(lanes, use_case="office") is None      # clean fleet → no advisory
    assert fleet_advisory(lanes, use_case=None) is None          # no use-case context → no advisory


def test_office_fleet_metric_boosts_a_managed_business_laptop():
    # Part A: a vPro/TPM/docking business laptop scores HIGHER than a plain one for an office query
    # (the office_fleet soft group fires in addition to business_class). use_case_fit is the live scorer.
    from src.app.services.recommend_candidate_classify import use_case_fit
    managed = {"sku": "M", "name": "Lenovo ThinkPad T14 vPro", "specs": {"use_case": "business", "tpm": True, "docking": "thunderbolt dock"}}
    plain = {"sku": "P", "name": "Lenovo ThinkPad E14", "specs": {"use_case": "business"}}
    fm = use_case_fit(managed, "10 laptops for work", profile_id="electronics")
    fp = use_case_fit(plain, "10 laptops for work", profile_id="electronics")
    assert fm["score_adjustment"] > fp["score_adjustment"]
    assert "office_fleet" in fm.get("soft_reasons", [])
