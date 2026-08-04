from src.app.services.budget_grammar import classify_budget_scope
from src.app.services.bulk_intent import (
    extract_quantity_span,
    requires_full_procurement_path,
)


def test_catalog_command_quantity_and_total_budget_are_both_recognized():
    query = (
        "Suggest 10 suitable laptops under a $25,000 total budget for Unreal Engine "
        "and Blender work"
    )

    assert extract_quantity_span(query, unit_nouns=("laptop",)) == (10, "10")
    assert classify_budget_scope(query) == "total"


def test_product_model_number_is_not_reclassified_as_quantity():
    assert extract_quantity_span("show Dell 15 laptops", unit_nouns=("laptop",)) is None


def test_at_least_count_with_hyphenated_workload_modifier():
    query = ("I'm starting a gaming studio with a total budget of $55,000. "
             "I need at least 20 game-development laptops for Unreal Engine.")

    assert extract_quantity_span(query, unit_nouns=("laptop",)) == (20, "20")
    assert classify_budget_scope(query) == "total"


def test_contextual_quantity_amendment_does_not_need_repeated_product_noun():
    assert extract_quantity_span(
        "Those are too weak, maybe reduce to 15 instead",
        unit_nouns=("laptop",),
    ) == (15, "15")


def test_catalog_fast_path_defers_to_full_economics_for_catalog_command_quantity():
    from types import SimpleNamespace

    plan = SimpleNamespace(quantity=None, availability_horizon_days=None)
    query = "Suggest 10 suitable laptops under a $25,000 total budget"

    assert requires_full_procurement_path(
        plan,
        query,
        unit_nouns=("laptop",),
    ) is True
