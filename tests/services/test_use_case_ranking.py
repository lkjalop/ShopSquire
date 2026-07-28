"""Regression: use-case ranking must be driven by the electronics adapter
(GPU tier + spec floors from the store profile), NOT a keyword regex.

Defect this locks down: a query containing "gaming" previously tagged EVERY
candidate `gaming_use_case_match` and boosted it, so an Intel-Arc 60Hz
productivity laptop (LP018) outranked a genuine RTX-3050 144Hz gaming laptop
(LAP-0020). The adapter now gates the use-case match on a discrete GPU tier and
the profile's spec floors, and the core delegates to it.
"""
from __future__ import annotations

import os

os.environ.setdefault("STORE_PROFILE_ID", "electronics")

from src.app.services.recommend_candidate_classify import (  # noqa: E402
    gpu_tier,
    use_case_fit,
)

# Real catalog rows (specs mirror the seeded electronics catalog).
LP018_ARC = {
    "sku": "LP018",
    "name": 'MSI Modern 15 H AI 15.6" FHD 60Hz Laptop',
    "specs": {"gpu": "Intel Arc Graphics", "refresh_hz": 60, "ram_gb": 16},
    "price_cents": 149900,
    "stock": 10,
}
LAP0020_RTX3050 = {
    "sku": "LAP-0020",
    "name": 'MSI Thin A15 15" FHD 144Hz Gaming Laptop (Ryzen 5) [GeForce RTX 3050]',
    "specs": {"gpu": "GeForce RTX 3050", "refresh_hz": 144, "ram_gb": 8},
    "price_cents": 179900,
    "stock": 5,
}
RTX4070 = {
    "sku": "LP-KAT",
    "name": "MSI Katana 15 Gaming Laptop",
    "specs": {"gpu": "GeForce RTX 4070", "refresh_hz": 165, "ram_gb": 16},
    "price_cents": 149900,
    "stock": 3,
}


def test_gpu_tier_arc_is_integrated_not_gaming():
    # The crux: Intel Arc is integrated tier, never discrete/gaming-grade.
    assert gpu_tier(LP018_ARC) == "integrated"
    assert gpu_tier({"specs": {"gpu": "Intel Iris Xe"}}) == "integrated"
    assert gpu_tier({"specs": {"gpu": "AMD Radeon 610M Graphics"}}) == "integrated"


def test_gpu_tier_discrete_bands():
    assert gpu_tier(LAP0020_RTX3050) == "entry"   # 3050
    assert gpu_tier({"specs": {"gpu": "GeForce RTX 4060"}}) == "mid"
    assert gpu_tier(RTX4070) == "high"            # 4070
    assert gpu_tier({"specs": {"gpu": "Radeon RX 7700"}}) == "high"


def test_gaming_match_requires_discrete_gpu_and_refresh():
    arc = use_case_fit(LP018_ARC, "gaming laptop")
    assert arc["use_case"] == "gaming"
    assert arc["meets"] is False
    assert "gaming_use_case_match" not in arc["reasons"]
    assert any(g.startswith("needs_discrete_gpu") for g in arc["gaps"])

    rtx = use_case_fit(LAP0020_RTX3050, "gaming laptop")
    assert rtx["meets"] is True
    assert rtx["reasons"][0] == "gaming_use_case_match"
    assert "discrete_gpu" in rtx["reasons"]
    assert "high_refresh_display" in rtx["reasons"]


def test_content_creation_requires_ram_floor():
    # 4K video editing needs >=16GB; a gaming RTX-3050/8GB must NOT claim the match.
    rtx3050_8gb = use_case_fit(LAP0020_RTX3050, "4k video editing and content creation")
    assert rtx3050_8gb["use_case"] == "video_editing"
    assert rtx3050_8gb["meets"] is False
    assert any(g.startswith("ram_below") for g in rtx3050_8gb["gaps"])

    rtx4070_16gb = use_case_fit(RTX4070, "4k video editing and content creation")
    assert rtx4070_16gb["meets"] is True
    assert rtx4070_16gb["reasons"][0] == "video_editing_use_case_match"


def test_generic_query_emits_no_use_case_match():
    fit = use_case_fit(LP018_ARC, "show me laptops")
    assert fit["use_case"] is None
    assert fit["reasons"] == []


def test_fast_path_ranks_discrete_above_integrated_for_gaming():
    # End-to-end on the real core scorer: the RTX-3050 144Hz gaming laptop must
    # score strictly higher than the Intel-Arc 60Hz laptop for a gaming query.
    from src.app.services.catalog_scoring import score_candidate

    hints = {"brand_hints": ["msi"], "use_case_hints": []}
    arc_score = score_candidate(
        row=LP018_ARC, query="gaming laptop", safe_hints=hints,
        budget_min=1300, budget_max=1800,
        use_case_fit=use_case_fit(LP018_ARC, "gaming laptop"),
    )
    rtx_score = score_candidate(
        row=LAP0020_RTX3050, query="gaming laptop", safe_hints=hints,
        budget_min=1300, budget_max=1800,
        use_case_fit=use_case_fit(LAP0020_RTX3050, "gaming laptop"),
    )
    assert rtx_score > arc_score, f"RTX-3050 {rtx_score} must beat Arc {arc_score}"
