import json

from src.app.services.case_research_plan import build_case_research_plan
from src.app.services.open_world_query_proposal import propose_open_world_queries


def _plan():
    plan = build_case_research_plan(
        "Can this laptop run coupled FEA and CFD simulations?", allow_open_world=True,
    )
    assert plan is not None
    return plan


def test_local_model_can_expand_vocabulary_but_gains_no_authority():
    result = {
        "interpretations": ["coupled finite element and computational fluid dynamics"],
        "shared_concepts": ["multiphysics simulation"],
        "divergent_axes": ["named solver", "vendor certification"],
        "queries": [
            {"axis": "concept_and_software", "query": "FEA CFD multiphysics solver official documentation"},
            {"axis": "requirements_and_compatibility", "query": "FEA CFD solver system requirements compatibility"},
            {"axis": "support_and_constraints", "query": "FEA CFD solver certified hardware support matrix"},
        ],
    }
    planned, receipt = propose_open_world_queries(
        _plan(), model_fn=lambda prompt, timeout: json.dumps(result),
    )

    assert receipt["status"] == "accepted"
    assert receipt["authority"] == "discovery_proposal_only"
    assert len(planned.discovery_queries) == 3
    assert planned.external_calls == 0
    assert planned.authority == "proposal_only"


def test_unanchored_or_hardware_inventing_model_output_falls_back():
    original = _plan()
    bad = {
        "interpretations": ["unrelated"], "shared_concepts": ["unrelated"],
        "queries": [
            {"axis": "concept_and_software", "query": "unrelated vendor documentation"},
            {"axis": "requirements_and_compatibility", "query": "unrelated 64GB requirements"},
        ],
    }
    planned, receipt = propose_open_world_queries(
        original, model_fn=lambda prompt, timeout: json.dumps(bad),
    )

    assert receipt["status"] == "rejected_or_unavailable"
    assert planned.discovery_queries == original.discovery_queries
    assert receipt["authority"] == "none"


def test_model_timeout_or_invalid_json_falls_back_without_hanging_contract():
    original = _plan()
    planned, receipt = propose_open_world_queries(
        original, model_fn=lambda prompt, timeout: "not-json", timeout_s=1,
    )
    assert planned == original
    assert receipt["status"] == "rejected_or_unavailable"


def test_model_timeout_falls_back_without_stranding_the_buyer():
    original = _plan()

    def timed_out(_prompt: str, _timeout_s: float) -> str:
        raise TimeoutError("local model deadline exceeded")

    planned, receipt = propose_open_world_queries(
        original, model_fn=timed_out, timeout_s=1,
    )

    assert planned == original
    assert receipt["status"] == "rejected_or_unavailable"
    assert receipt["reason"] == "TimeoutError"
    assert receipt["authority"] == "none"
