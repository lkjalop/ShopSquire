"""M2-B1: requirement RANGES with provenance + surfaced conflicts (constraints.py).

The review's exact scenario is the spine: 'nothing over 8GB RAM' (stated ceiling) meeting the
university KB floor of 16 must become a SURFACED CONFLICT — never a silent inversion in either
direction. A compatible floor+ceiling must coexist as one range (the one-slot shape physically
couldn't hold both)."""
from src.app.services.recommendation_core.constraints import (
    RequirementConstraint,
    as_dicts,
    conflicts,
    from_op,
    from_op_map,
    merge,
    merge_maps,
    project,
)


# ── single-key merges ────────────────────────────────────────────────────────────

def test_floor_plus_floor_takes_max():
    c = merge(from_op("ram_gb", ">=", 8, "use_case:university"),
              from_op("ram_gb", ">=", 16, "title:game"))
    assert c.lower == 16 and c.upper is None and not c.is_conflict
    assert set(c.provenance) == {"use_case:university", "title:game"}


def test_ceiling_plus_ceiling_takes_min():
    c = merge(from_op("ram_gb", "<=", 32, "stated"), from_op("ram_gb", "<=", 16, "stated"))
    assert c.upper == 16 and c.lower is None


def test_floor_plus_ceiling_is_a_range_both_enforced():
    # THE one-slot bug: 'at least 16' + 'no more than 32' — the old shape dropped one bound.
    c = merge(from_op("ram_gb", ">=", 16, "use_case:university"),
              from_op("ram_gb", "<=", 32, "stated"))
    assert (c.lower, c.upper) == (16, 32) and not c.is_conflict
    assert c.predicates() == [(">=", 16.0), ("<=", 32.0)]     # BOTH gate


def test_conflict_surfaced_never_silently_inverted():
    # 'nothing over 8GB' (stated) vs university floor 16 → CONFLICT, no predicates, both sources
    c = merge(from_op("ram_gb", ">=", 16, "use_case:university"),
              from_op("ram_gb", "<=", 8, "stated"))
    assert c.is_conflict
    assert c.predicates() == []                                # contradictions never gate
    assert set(c.provenance) == {"use_case:university", "stated"}


def test_equality_pins_both_bounds():
    c = from_op("ram_gb", "==", 16, "stated")
    assert (c.lower, c.upper) == (16, 16) and not c.is_conflict
    assert c.predicates() == [(">=", 16.0), ("<=", 16.0)]


def test_strict_edge_tie_is_conflict():
    # '> 16' merged with '<= 16' is an empty range
    c = merge(from_op("ram_gb", ">", 16, "stated"), from_op("ram_gb", "<=", 16, "stated"))
    assert c.is_conflict


# ── map-level helpers (the pipeline shapes) ──────────────────────────────────────

def test_from_op_map_accepts_both_shapes():
    m1 = from_op_map({"ram_gb": (">=", 8)}, "stated")                      # single tuple
    m2 = from_op_map({"ram_gb": [(">=", 8), ("<=", 32)]}, "stated")        # predicate list
    assert m1["ram_gb"].lower == 8
    assert (m2["ram_gb"].lower, m2["ram_gb"].upper) == (8, 32)


def test_merge_maps_and_project_review_scenario():
    kb = from_op_map({"ram_gb": (">=", 16), "storage_gb": (">=", 256)}, "use_case:university")
    stated = from_op_map({"ram_gb": ("<=", 8), "refresh_hz": (">=", 144)}, "stated")
    merged = merge_maps(kb, stated)
    # ram conflicts → surfaced + excluded from gating; the others gate normally
    assert [c["key"] for c in conflicts(merged)] == ["ram_gb"]
    proj = project(merged)
    assert "ram_gb" not in proj
    assert proj["storage_gb"] == [(">=", 256.0)] and proj["refresh_hz"] == [(">=", 144.0)]
    # full fidelity for the trace
    d = as_dicts(merged)["ram_gb"]
    assert d["conflict"] is True and set(d["provenance"]) == {"use_case:university", "stated"}


def test_evaluate_requirements_handles_ranges():
    from src.app.services.attribute_registry import evaluate_requirements
    attrs = {"ram_gb": 16}
    ok = evaluate_requirements(attrs, {"ram_gb": [(">=", 8), ("<=", 32)]})
    assert ok["overall"] == "meets" and ok["per_key"]["ram_gb"] is True
    over = evaluate_requirements(attrs, {"ram_gb": [(">=", 8), ("<=", 12)]})
    assert over["overall"] == "fails"
    # tuple shape still accepted (back-compat)
    legacy = evaluate_requirements(attrs, {"ram_gb": (">=", 8)})
    assert legacy["overall"] == "meets"


def test_resolver_end_to_end_stated_ceiling_vs_kb_floor():
    """The B1 acceptance: resolve() with a KB use-case floor + a stated ceiling surfaces the
    conflict and never gates on the contradiction."""
    from src.app.services.recommendation_core.intent_resolver import resolve
    out = resolve(["university"], {"ram_gb": [("<=", 8)]}, query=None)
    ram_conflicts = [c for c in out["conflicts"] if c["key"] == "ram_gb"]
    if ram_conflicts:                       # university KB carries a ram floor > 8
        assert "ram_gb" not in out["requirements"]
        assert "stated" in ram_conflicts[0]["provenance"]
    else:                                   # KB floor ≤ 8 → an honest range instead
        assert out["requirements"]["ram_gb"][-1] == ("<=", 8.0)
    # constraints block always carries full fidelity
    assert "ram_gb" in out["constraints"]
