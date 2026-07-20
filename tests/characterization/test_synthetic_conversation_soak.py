from tests.characterization.synthetic_conversation_soak import (
    TurnSpec,
    _apply_cart_plan,
    _dimension_summary,
    _error_dimension,
    _percentile,
    _session_from,
    build_context_journeys,
    build_journeys,
    build_lifecycle_journeys,
)


def test_build_journeys_hits_exact_turn_target_and_is_deterministic():
    a = build_journeys(203, seed=7)
    b = build_journeys(203, seed=7)
    assert sum(len(j.turns) for j in a) == 203
    assert [(j.family, [t.query for t in j.turns]) for j in a] == [
        (j.family, [t.query for t in j.turns]) for j in b]


def test_build_journeys_supports_explicit_stress_shape():
    journeys = build_journeys(225, seed=7, turns_per_journey=3)
    assert len(journeys) == 75
    assert all(len(j.turns) == 3 for j in journeys)


def test_long_context_and_lifecycle_shapes_are_real_not_repeated_five_turns():
    context = build_context_journeys(20, seed=7)
    lifecycle = build_lifecycle_journeys(14, seed=7)
    assert len(context) == 20 and all(len(j.turns) == 10 for j in context)
    assert len(lifecycle) == 14 and all(len(j.turns) == 15 for j in lifecycle)
    assert all(j.family == "lifecycle_procurement" for j in lifecycle)


def test_matrix_covers_requested_surfaces():
    journeys = build_journeys(200)
    families = {j.family for j in journeys}
    assert {"high_school", "university", "ai_creator", "retiree", "graphics_tablet",
            "office_per_unit", "office_total", "gaming", "support", "cart_changes"} <= families
    turns = [t for j in journeys for t in j.turns]
    assert any(t.budget_scope == "per_unit" for t in turns)
    assert any(t.budget_scope == "total" for t in turns)
    assert any(t.kind == "cart" for t in turns)


def test_apply_cart_plan_is_side_effect_free():
    class Op:
        action = "set_quantity"
        target_skus = ("A",)
        quantity = 3

    class Plan:
        ops = (Op(),)

    original = [{"sku": "A", "quantity": 1}]
    updated = _apply_cart_plan(original, Plan())
    assert original[0]["quantity"] == 1
    assert updated[0]["quantity"] == 3


def test_percentile_nearest_rank():
    assert _percentile([1, 2, 3, 4], 50) == 2
    assert _percentile([1, 2, 3, 4], 95) == 4


def test_session_emulates_production_brand_persistence():
    class Core:
        products = []
        extras = {
            "decision": {
                "node_handle": "el-6-1",
                "exclude_brand": "Apple",
                "brand_filter": "Lenovo",
                "preferred_brand": "Dell",
            },
            "constraints_used": {},
        }

    accepted = _session_from(Core())["accepted_constraints"]
    assert accepted["exclude_brand"] == "Apple"
    assert accepted["brand_filter"] == "Lenovo"
    assert accepted["preferred_brand"] == "Dell"


def test_soak_dimensions_do_not_mix_lane_calibration_with_safety():
    rows = [
        {"turn": 0, "errors": ["lane:SEARCH:expected:FILTER"]},
        {"turn": 1, "errors": ["node:None:expected_contains:Laptop"]},
        {"turn": 2, "errors": ["irreversible_action_executed"]},
        {"turn": 2, "errors": []},
    ]
    summary = _dimension_summary(rows)
    assert summary["routing_calibration"]["flagged_turns"] == 1
    assert summary["continuity"]["flagged_turns"] == 1
    assert summary["semantic_safety"]["flagged_turns"] == 1
    assert summary["relevance"]["measured"] is False
    assert _error_dimension("node:x", turn=0) == "semantic_safety"
