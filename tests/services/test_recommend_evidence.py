"""Per-pick narration evidence: typed metrics derived from candidate data + profile markers, and an
answer-level summary that refuses a 'best for work' claim when no office-grade pick qualified."""
from __future__ import annotations

import os

os.environ.setdefault("STORE_PROFILE_ID", "electronics")

from src.app.platform.store_profile import profile_slot  # noqa: E402
from src.app.services.recommend_evidence import (  # noqa: E402
    build_pick_evidence,
    render_evidence_block,
    summarize_answer_evidence,
)


def _marker(group):
    sm = profile_slot("use_case_soft_markers", default={}) or {}
    if group in sm:
        return sm[group]
    return (profile_slot("evidence_markers", default={}) or {}).get(group, [])


def test_price_fit_within_over_under():
    within = build_pick_evidence({"sku": "A", "price": 1500}, budget_min=1300, budget_max=1800, marker_fn=_marker)
    over = build_pick_evidence({"sku": "B", "price": 2200}, budget_min=1300, budget_max=1800, marker_fn=_marker)
    under = build_pick_evidence({"sku": "C", "price": 900}, budget_min=1300, budget_max=1800, marker_fn=_marker)
    assert within["price_fit"]["status"] == "within"
    assert over["price_fit"]["status"] == "over"
    assert under["price_fit"]["status"] == "under"


def test_inventory_fit_from_stock_fields():
    ev = build_pick_evidence({"sku": "A", "stock_status": "in_stock", "stock_level": 12}, marker_fn=_marker)
    assert ev["inventory_fit"]["status"] == "in_stock" and "12" in ev["inventory_fit"]["detail"]
    out = build_pick_evidence({"sku": "B", "stock_status": "out_of_stock"}, marker_fn=_marker)
    assert out["inventory_fit"]["status"] == "out_of_stock"


def test_office_and_fleet_fit_from_markers():
    managed = build_pick_evidence(
        {"sku": "TP", "name": "Lenovo ThinkPad T14 vPro", "specs": {"use_case": "business", "docking": "thunderbolt dock"}},
        marker_fn=_marker)
    assert managed["office_fit"]["status"] == "office_grade"
    assert managed["fleet_fit"]["status"] == "managed"
    assert managed["docking"]["status"] == "yes"
    consumer = build_pick_evidence({"sku": "KT", "name": "MSI Katana Gaming Laptop", "specs": {"gaming_style": True}},
                                   marker_fn=_marker)
    assert consumer["office_fit"]["status"] == "consumer" and consumer["fleet_fit"]["status"] == "unmanaged"


def test_os_ecosystem_detected_from_profile_groups():
    mac = build_pick_evidence({"sku": "MB", "name": "Apple MacBook Air (Apple M3)"}, marker_fn=_marker)
    cb = build_pick_evidence({"sku": "CB", "name": "Acer Chromebook Spin"}, marker_fn=_marker)
    assert mac["os_ecosystem"]["status"] == "macOS"
    assert cb["os_ecosystem"]["status"] == "ChromeOS"


def test_risk_penalties_from_factors_and_exclusions():
    ev = build_pick_evidence({"sku": "X", "factors": {"negative": ["-brand_mismatch"]}, "exclusions": ["consumer_gaming_aesthetic"]},
                             marker_fn=_marker)
    assert ev["risk_penalties"]["status"] == "present"
    assert "brand_mismatch" in ev["risk_penalties"]["detail"] and "exclusion:consumer_gaming_aesthetic" in ev["risk_penalties"]["detail"]


def test_answer_evidence_refuses_work_claim_when_only_gaming():
    res = [{"sku": "KT", "name": "MSI Katana Gaming Laptop", "price": 1899, "specs": {"gaming_style": True}}]
    ae = summarize_answer_evidence(res, budget_min=1300, budget_max=1800, use_case="office", marker_fn=_marker)
    assert ae["office_grade_count"] == 0 and ae["work_suitable"] is False
    block = render_evidence_block(ae)
    assert "do NOT claim" in block and "sourcing/procurement" in block


def test_answer_evidence_allows_work_claim_with_office_grade_pick():
    res = [{"sku": "TP", "name": "Lenovo ThinkPad T14 vPro", "price": 1650, "specs": {"use_case": "business"}}]
    ae = summarize_answer_evidence(res, budget_min=1300, budget_max=1800, use_case="office", marker_fn=_marker)
    assert ae["office_grade_count"] >= 1 and ae["work_suitable"] is True


def test_render_block_lists_at_least_three_metrics_per_pick():
    res = [{"sku": "TP", "name": "Lenovo ThinkPad T14 vPro", "price": 1650,
            "specs": {"use_case": "business", "docking": "thunderbolt dock"}, "stock_status": "in_stock", "stock_level": 5}]
    ae = summarize_answer_evidence(res, budget_min=1300, budget_max=1800, use_case="office", marker_fn=_marker)
    block = render_evidence_block(ae)
    # the narration block names the pick with several grounded metrics (price_fit/office_fit/fleet_fit/...)
    metric_hits = sum(1 for m in ("price_fit", "office_fit", "fleet_fit", "inventory_fit", "os_ecosystem") if m in block)
    assert metric_hits >= 3
