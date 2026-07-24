import json

import pytest

from tests.characterization.synthetic_conversation_soak import (
    JourneySpec,
    TurnSpec,
    _apply_cart_plan,
    _dimension_summary,
    _effective_decision,
    _error_dimension,
    _percentile,
    _resume_checkpoint,
    _session_from,
    build_context_journeys,
    build_journeys,
    build_lifecycle_journeys,
)


def test_resume_checkpoint_keeps_only_complete_matching_journeys(tmp_path):
    checkpoint = tmp_path / "soak.partial.jsonl"
    rows = [
        {"seed": 7, "suite": "breadth", "journey": 0, "turn": 0},
        {"seed": 7, "suite": "breadth", "journey": 0, "turn": 1},
        {"seed": 7, "suite": "breadth", "journey": 1, "turn": 0},
    ]
    checkpoint.write_text(
        "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8",
    )
    journeys = [
        JourneySpec("done", "p", "a", (TurnSpec("one"), TurnSpec("two"))),
        JourneySpec("partial", "p", "a", (TurnSpec("one"), TurnSpec("two"))),
    ]

    kept, complete = _resume_checkpoint(
        checkpoint, seed=7, suite="breadth", journeys=journeys,
    )

    assert complete == {0}
    assert [(row["journey"], row["turn"]) for row in kept] == [(0, 0), (0, 1)]
    assert len(checkpoint.read_text(encoding="utf-8").splitlines()) == 2


def test_resume_checkpoint_rejects_a_different_run(tmp_path):
    checkpoint = tmp_path / "soak.partial.jsonl"
    checkpoint.write_text(
        json.dumps({"seed": 8, "suite": "breadth", "journey": 0, "turn": 0}) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="different seed or suite"):
        _resume_checkpoint(
            checkpoint,
            seed=7,
            suite="breadth",
            journeys=[JourneySpec("one", "p", "a", (TurnSpec("one"),))],
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
        lane = "FILTER"
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


def test_session_keeps_active_procurement_across_filter_refinement():
    class Procurement:
        lane = "PROCUREMENT"
        products = []
        extras = {"decision": {"subject_action": "continue"}, "constraints_used": {}}

    class Filter:
        lane = "FILTER"
        products = []
        extras = {"decision": {"subject_action": "continue"}, "constraints_used": {}}

    session = _session_from(Procurement())
    refined = _session_from(Filter(), session)
    assert refined["prior_lane"] == "FILTER"
    assert refined["active_workflow_lane"] == "PROCUREMENT"


def test_session_merge_does_not_erase_subject_or_constraints_on_explanation_turn():
    prior = {
        "prior_node": "el-6-1",
        "shortlist_skus": ["LAP-1"],
        "accepted_constraints": {
            "quantity": 25,
            "total_budget_cents": 4100000,
            "budget_scope": "total",
            "exclude_brand": "Apple",
        },
    }

    class Core:
        lane = "EXPLAIN"
        products = []
        extras = {"decision": {"lane": "EXPLAIN"}, "constraints_used": {}}

    merged = _session_from(Core(), prior)
    assert merged["prior_lane"] == "EXPLAIN"
    assert {key: value for key, value in merged.items() if key != "prior_lane"} == prior


def test_effective_decision_reads_authorized_prior_state_for_nodeless_turn():
    class Core:
        extras = {"decision": {"budget_scope": "unknown"}}

    effective = _effective_decision(Core(), {
        "prior_node": "el-6-1",
        "accepted_constraints": {"quantity": 25, "budget_scope": "total"},
    })
    assert effective["node_handle"] == "el-6-1"
    assert effective["quantity"] == 25
    assert effective["budget_scope"] == "total"


def test_soak_dimensions_do_not_mix_lane_calibration_with_safety():
    rows = [
        {"turn": 0, "errors": ["lane:SEARCH:expected:FILTER"]},
        {"turn": 0, "errors": ["products:empty"]},
        {"turn": 1, "errors": ["node:None:expected_contains:Laptop"]},
        {"turn": 2, "errors": ["irreversible_action_executed"]},
        {"turn": 2, "errors": []},
    ]
    summary = _dimension_summary(rows)
    assert summary["routing_calibration"]["flagged_turns"] == 1
    assert summary["catalog_coverage"]["flagged_turns"] == 1
    assert summary["continuity"]["flagged_turns"] == 1
    assert summary["semantic_safety"]["flagged_turns"] == 1
    assert summary["relevance"]["measured"] is False
    assert _error_dimension("node:x", turn=0) == "semantic_safety"
    assert _error_dimension("products:empty", turn=4) == "catalog_coverage"
