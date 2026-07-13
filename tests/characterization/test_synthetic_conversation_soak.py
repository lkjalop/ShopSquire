from tests.characterization.synthetic_conversation_soak import (
    TurnSpec,
    _apply_cart_plan,
    _percentile,
    _session_from,
    build_journeys,
)


def test_build_journeys_hits_exact_turn_target_and_is_deterministic():
    a = build_journeys(203, seed=7)
    b = build_journeys(203, seed=7)
    assert sum(len(j.turns) for j in a) == 203
    assert [(j.family, [t.query for t in j.turns]) for j in a] == [
        (j.family, [t.query for t in j.turns]) for j in b]


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


def test_session_emulates_production_brand_persistence_gap():
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
    assert "exclude_brand" not in accepted
    assert "brand_filter" not in accepted
    assert "preferred_brand" not in accepted
