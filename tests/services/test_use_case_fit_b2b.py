"""use_case_fit B2B/fleet adjustment (the LIVE fast-path scorer recommend.py:_score_row uses).

The "office" use-case has no hard spec floor, so every laptop MEETS it and scores +35 identically — gaming
included. This adds a profile-driven soft/exclusion score_adjustment so business/productivity machines
outrank consumer gaming SKUs for a work-fleet query, without putting any vocabulary in the core scorer.

Regression for the demo finding that "10 work laptops $1300-$1500" surfaced gaming laptops.
"""
from __future__ import annotations

from src.app.services.recommend_candidate_classify import use_case_fit

_GAMING = {"name": "MSI Katana 15 Gaming Laptop (RTX 4070)",
           "specs": {"gaming_style": True, "use_case": "gaming", "ram_gb": 16, "refresh_hz": 144}}
_PRODUCTIVITY = {"name": "HP Pavilion 15 (Core i7)",
                 "specs": {"gaming_style": False, "use_case": "productivity", "ram_gb": 16, "storage_gb": 512}}
_BUSINESS_LINE = {"name": "Dell Latitude 5440 Business Laptop",
                  "specs": {"gaming_style": False, "use_case": "productivity", "ram_gb": 16}}


def _fit(c, q):
    return use_case_fit(c, q, profile_id="electronics")


def test_work_laptops_plural_resolves_office():
    # the plural-`s` pattern fix: "10 work laptops" must resolve the office use-case (it didn't before).
    assert _fit(_PRODUCTIVITY, "10 work laptops 1300-1500")["use_case"] == "office"


def test_office_query_demotes_gaming_below_business():
    q = "20 laptops for work in 2 weeks"
    g = _fit(_GAMING, q)
    p = _fit(_PRODUCTIVITY, q)
    b = _fit(_BUSINESS_LINE, q)
    # all MEET (office has no hard floor) — separation comes entirely from the adjustment
    assert g["meets"] and p["meets"] and b["meets"]
    assert g["score_adjustment"] < 0 and "consumer_gaming_aesthetic" in g["exclusions"]
    assert p["score_adjustment"] > 0 and "productivity_grade" in p["soft_reasons"]
    assert b["score_adjustment"] > p["score_adjustment"]  # business-line brand stacks on productivity
    # net fast-path effect (+35 meets + adjustment) keeps business/productivity above gaming
    assert (35 + b["score_adjustment"]) > (35 + p["score_adjustment"]) > (35 + g["score_adjustment"])


def test_office_fleet_metrics_boost_a_managed_business_laptop():
    # stronger office metrics: a vPro/TPM/docking machine outranks a plain business laptop for a work query
    # (the office_fleet soft group stacks on business_class/productivity_grade). Profile-driven; core agnostic.
    managed = {"name": "Lenovo ThinkPad T14 vPro", "specs": {"use_case": "business", "tpm": True, "docking": "thunderbolt dock", "ram_gb": 16}}
    plain = {"name": "Lenovo ThinkPad E14", "specs": {"use_case": "business", "ram_gb": 16}}
    q = "10 laptops for work 1300-1500"
    fm, fp = _fit(managed, q), _fit(plain, q)
    assert "office_fleet" in fm["soft_reasons"] and "office_fleet" not in fp["soft_reasons"]
    assert fm["score_adjustment"] > fp["score_adjustment"]


def test_gaming_query_does_not_demote_gaming():
    # the exclusion is office-only; a genuine gaming query must NOT carry the consumer-gaming penalty.
    g = _fit(_GAMING, "best gaming laptop for esports")
    assert g["use_case"] == "gaming"
    assert g["score_adjustment"] == 0.0 and not g["exclusions"]


def test_generic_query_has_no_adjustment():
    f = _fit(_PRODUCTIVITY, "a laptop")
    assert f["use_case"] is None and f["score_adjustment"] == 0.0
