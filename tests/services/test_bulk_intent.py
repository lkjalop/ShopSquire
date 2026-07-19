from src.app.services.budget_grammar import classify_budget_scope
from src.app.services.bulk_intent import extract_quantity_span


def test_catalog_command_quantity_and_total_budget_are_both_recognized():
    query = (
        "Suggest 10 suitable laptops under a $25,000 total budget for Unreal Engine "
        "and Blender work"
    )

    assert extract_quantity_span(query, unit_nouns=("laptop",)) == (10, "10")
    assert classify_budget_scope(query) == "total"


def test_product_model_number_is_not_reclassified_as_quantity():
    assert extract_quantity_span("show Dell 15 laptops", unit_nouns=("laptop",)) is None


def test_catalog_fast_path_defers_to_full_economics_for_catalog_command_quantity():
    from types import SimpleNamespace
    from src.app.routers.recommend import _requires_full_path_for_bulk

    plan = SimpleNamespace(quantity=None, availability_horizon_days=None)
    query = "Suggest 10 suitable laptops under a $25,000 total budget"

    assert _requires_full_path_for_bulk(plan, query) is True
