"""Unified use-case registry (Track E) — the hybrid coarse→variant resolution, the high_school
worked example, and a behaviour-neutral check that the migrated floors match the live legacy KB."""
import json
from pathlib import Path

from src.app.services import use_case_registry as R


def test_coarse_resolves_baseline_and_floor():
    got = R.resolve("electronics", "gaming")
    assert got["variant"] is None
    assert got["specs"]["ram_gb_min"] == 16 and got["specs"]["gpu_tier"] == 2
    assert got["budget_floor"] == 500
    assert "el-6-11-2" in got["host_nodes"]


def test_variant_overrides_baseline_and_floor():
    aaa = R.resolve("electronics", "gaming", "aaa_heavy")
    assert aaa["variant"] == "aaa_heavy"
    assert aaa["specs"]["gpu_tier"] == 4 and aaa["specs"]["gpu_vram_gb_min"] == 8
    assert aaa["budget_floor"] == 1200                    # variant floor wins over coarse 500
    assert aaa["specs"]["ram_gb_min"] == 16               # baseline kept where variant is silent


def test_unknown_variant_falls_back_to_baseline():
    got = R.resolve("electronics", "gaming", "no_such_variant")
    assert got["variant"] is None and got["budget_floor"] == 500   # coarse baseline, never invented


def test_unknown_coarse_is_none():
    assert R.resolve("electronics", "not_a_use_case") is None


def test_high_school_is_variants_not_one_floor():
    """The '300 vs 400 conflict' dissolves: high_school floor depends on INTENT (schooling vs
    light vs serious gaming), each a variant — the user's product insight, encoded."""
    school = R.resolve("electronics", "high_school", "schooling")
    light = R.resolve("electronics", "high_school", "light_gaming")
    serious = R.resolve("electronics", "high_school", "serious_gaming")
    assert school["budget_floor"] == 400 and school["specs"]["gpu_tier"] == 0
    assert light["budget_floor"] == 600 and light["specs"]["gpu_tier"] == 1
    assert serious["budget_floor"] == 900 and serious["specs"]["refresh_hz_min"] == 144


def test_high_school_content_advisory_is_advisory_only():
    adv = R.content_advisory("electronics", "high_school")
    assert adv and adv["persona"] == "minor"
    assert "never a hard block" in adv["note"].lower()    # advisory, not an age-gate


def test_migration_is_behaviour_neutral_on_overlapping_floors():
    """The floors migrated from the live workhorse (use_case_knowledge_base.json) must match, so
    switching consumers onto the registry changes no behaviour for the overlapping use-cases."""
    legacy = json.loads((Path("config/use_case_knowledge.json")).read_text(encoding="utf-8"))
    lf = {k: v.get("min_price_floor") for k, v in (legacy.get("use_cases") or {}).items()}
    # coarse ai_ml_workstation + a couple of student variants map 1:1 to legacy fine keys
    assert R.resolve("electronics", "ai_ml_workstation")["budget_floor"] == lf["ai_ml_workstation"]  # 1500
    assert R.resolve("electronics", "student", "engineering")["budget_floor"] == lf["engineering_student"]  # 1000
    assert R.resolve("electronics", "gaming", "aaa_heavy")["budget_floor"] == lf["gaming_aaa_heavy"]  # 1200


def test_scaffold_verticals_load_empty():
    """home/appliances/furniture scaffolds load (bound to real taxonomy) with no use_cases yet —
    the breadth FOUNDATION exists; depth comes after electronics ships."""
    for v in ("home", "appliances", "furniture"):
        assert R.list_use_cases(v) == []
        assert R.load_use_cases(v).get("host_nodes")      # bound to a taxonomy root
