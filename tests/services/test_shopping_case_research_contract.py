from src.app.services.case_research_plan import build_case_research_plan
from src.app.services.shopping_case_research_contract import (
    project_research_execution_contract,
)


def test_enrolled_and_open_world_lanes_are_explicit_and_non_authoritative():
    enrolled = build_case_research_plan("Blender rendering")
    unresolved = build_case_research_plan(
        "vendor certified hardware for a novel multiphysics solver",
        allow_open_world=True,
    )
    assert enrolled is not None and unresolved is not None

    enrolled_contract = project_research_execution_contract(enrolled)
    assert enrolled_contract.execution_lane == "enrolled_official_sources"
    assert enrolled_contract.publisher_approval_required is False
    assert enrolled_contract.source_candidate_ids

    unresolved_contract = project_research_execution_contract(unresolved)
    assert unresolved_contract.execution_lane == "publisher_resolution"
    assert unresolved_contract.publisher_approval_required is True
    assert unresolved_contract.source_candidate_ids == []
    assert unresolved_contract.qualification_authority == "none"
    assert unresolved_contract.cart_authority == "none"
