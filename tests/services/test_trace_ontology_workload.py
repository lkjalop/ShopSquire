from types import SimpleNamespace

from src.app.services.recommendation_core.trace_ontology import build_execution_steps


def test_trace_separates_workload_evidence_from_authorization():
    core = SimpleNamespace(
        lane="SEARCH",
        degraded=False,
        products=[],
        clarify=[{"id": "workload_requirements"}],
        extras={
            "decision": {
                "source": "model",
                "model_proposal": {
                    "workload_entities": [
                        {"kind": "software", "name": "Siemens NX 2025"},
                    ],
                },
                "authorization_changes": [],
            },
            "intent": {
                "title_requirements": {
                    "external_workload_evidence": {
                        "live_allowed": True,
                        "items": [{
                            "kind": "software",
                            "requested_name": "Siemens NX 2025",
                            "status": "not_resolved",
                        }],
                    },
                },
            },
            "workload_authorization": {
                "status": "blocked",
                "reason": "named_workload_evidence_unresolved",
                "state_prevented": ["catalog_qualification", "supplier_rfq"],
            },
            "stage_results": [],
        },
    )

    by_id = {item["id"]: item for item in build_execution_steps(core)}

    assert by_id["model-proposal"]["authority"] == "proposes"
    assert by_id["workload-evidence"]["kind"] == "connector"
    assert by_id["workload-evidence"]["status"] == "incomplete"
    assert by_id["workload-authorization"]["kind"] == "gate"
    assert by_id["workload-authorization"]["status"] == "blocked"
    assert "supplier_rfq" in by_id["workload-authorization"]["output"]["state_prevented"]


def test_trace_projects_generic_research_plan_evidence_and_authorization():
    core = SimpleNamespace(
        lane="SEARCH",
        degraded=False,
        products=[],
        clarify=[{"id": "external_research_consent"}],
        extras={
            "decision": {"source": "model", "model_proposal": {}, "authorization_changes": []},
            "plan": {
                "research_plan": {
                    "version": "research-plan-v1",
                    "subject_spans": ["predictive maintenance simulation"],
                    "evidence_needs": [{
                        "need_id": "requirements_1",
                        "subject_span": "predictive maintenance simulation",
                        "claim_type": "recommended_requirements",
                        "provider_capability": "official_requirements",
                    }],
                    "material_slots": [],
                    "external_research_authorized": False,
                },
            },
            "semantic_evidence": {
                "selected": ["concept_resolution"],
                "source_health": "degraded",
                "ms": 12,
                "legs": {
                    "concept_resolution": {
                        "found": False,
                        "data": {"status": "consent_required"},
                    },
                },
            },
            "semantic_resolution": {
                "outcome": "clarify",
                "catalog_authority": "blocked",
                "state_prevented": ["catalog_recommendation", "supplier_enquiry"],
            },
            "stage_results": [],
        },
    )

    by_id = {item["id"]: item for item in build_execution_steps(core)}

    assert by_id["research-plan"]["authority"] == "plans"
    assert by_id["research-plan"]["status"] == "consent_required"
    assert by_id["buyer-research-consent"]["kind"] == "buyer_input"
    assert by_id["buyer-research-consent"]["authority"] == "grants_research_scope"
    assert by_id["buyer-research-consent"]["output"]["commercial_authority_granted"] is False
    assert by_id["semantic-evidence"]["kind"] == "connector"
    assert by_id["semantic-evidence"]["latency_ms"] == 12
    assert by_id["semantic-authorization"]["kind"] == "gate"
    assert by_id["semantic-authorization"]["status"] == "blocked"


def test_trace_projects_relative_quantity_as_pending_commercial_authorization():
    core = SimpleNamespace(
        lane="SEARCH",
        degraded=False,
        products=[],
        clarify=[],
        extras={
            "decision": {"source": "model", "model_proposal": {}, "authorization_changes": []},
            "case_obligations": [{
                "kind": "quantity_change",
                "status": "pending_confirmation",
                "operation": "decrease",
                "amount": 10,
                "prior_value": 30,
                "proposed_value": 20,
            }],
            "conversation_case_context": {
                "prior_quantity": 30,
                "total_budget_cents": 7_500_000,
                "currency": "AUD",
            },
            "stage_results": [],
        },
    )

    by_id = {item["id"]: item for item in build_execution_steps(core)}

    reducer = by_id["commercial-case-reducer"]
    assert reducer["kind"] == "gate"
    assert reducer["status"] == "pending_confirmation"
    assert reducer["output"]["prior_quantity"] == 30
    assert reducer["output"]["obligations"][0]["proposed_value"] == 20
    assert reducer["output"]["commercial_authority_granted"] is False
