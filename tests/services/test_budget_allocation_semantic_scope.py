"""A typed whole-order allocation is not a new software workload."""
import pytest

from src.app.services.recommendation_core.semantic_coverage import unresolved_purpose_proposal


@pytest.mark.parametrize("query,node_path", [
    ("Change my budget to 10,000 USD total for all 8 laptops.", "Electronics > Computers > Laptops"),
    ("My budget is EUR 2000 total for all 4 office chairs.", "Furniture > Office Furniture > Office Chairs"),
    ("Keep AUD 5000 total for all 20 valves.", "Industrial > Fluid Control > Valves"),
    ("Change my budget to USD 10000 total for all eight laptops.", "Electronics > Computers > Laptops"),
])
def test_budget_allocation_to_the_current_category_has_no_material_workload(query, node_path):
    result = unresolved_purpose_proposal(query=query, use_cases=(), workload_entities=(), node_path=node_path)
    assert not result.get("concepts")
    assert result.get("proposed_action") != "research_then_clarify"


@pytest.mark.parametrize("query", [
    "I need laptops for all 8 unfamiliar multiphysics solvers, USD 10000 total.",
    "I need laptops for eight independently certified simulation workloads, USD 10000 total.",
    "Change my budget to USD 10000 total for all 8 laptops running an unfamiliar nuclear solver.",
])
def test_budget_language_cannot_remove_an_actual_unresolved_purpose(query):
    result = unresolved_purpose_proposal(query=query, use_cases=(), workload_entities=(),
                                        node_path="Electronics > Computers > Laptops")
    assert result["concepts"]
    assert result["proposed_action"] == "research_then_clarify"
