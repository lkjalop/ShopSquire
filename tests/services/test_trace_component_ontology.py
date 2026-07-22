from src.app.services.trace_component_ontology import classify_trace_component


def test_ordinary_legacy_agent_ids_are_not_presented_as_agents():
    assert classify_trace_component("agent", "Candidate_Retrieval_Agent") == {
        "kind": "connector", "authority": "retrieves", "label": "Candidate Retrieval",
        "legacy_id": "Candidate_Retrieval_Agent",
    }
    assert classify_trace_component("agent", "Copywriting_Agent")["kind"] == "stage"
    assert classify_trace_component("agent", "Trace_Persistence_Agent")["kind"] == "observer"


def test_model_directed_component_reserves_agent_role():
    component = classify_trace_component("agent", "Recommendation_Agent")
    assert component["kind"] == "agent"
    assert component["authority"] == "proposes"


def test_procurement_is_a_workflow_not_a_free_agent():
    component = classify_trace_component("agent", "Procurement_Agent")
    assert component["kind"] == "workflow"
    assert component["authority"] == "coordinates"
