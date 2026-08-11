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
        clarify=[{
            "id": "execution_location",
            "text": "Will the workload run locally, remotely, or in a hybrid setup?",
            "missing_slots": ["execution-location"],
            "selection_policy": "expected_decision_impact",
            "decision_impacts": ["architecture", "capability", "product_set"],
        }],
        extras={
            "decision": {"source": "model", "model_proposal": {}, "authorization_changes": []},
            "plan": {
                "semantic_authority_state": "uninterpreted_material",
                "needs_concept_resolution": True,
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
            "research_trigger_shadow": {
                "state": "unresolved_workload",
                "score": 0.72,
                "recommendation": "research_candidate",
                "features": {"semantic_gap": 1.0},
                "reasons": ["material_semantic_concept"],
                "mode": "observer",
                "calibration_status": "uncalibrated_shadow",
                "authoritative": False,
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
            "semantic_requirement_compilation": {
                "status": "accepted",
                "accepted_claim_count": 2,
                "compiled_requirements": {
                    "ram_gb": {"op": ">=", "value": 32},
                    "gpu_vram_gb": {"op": ">=", "value": 8},
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

    assert by_id["platform-authorization"]["output"]["semantic_authority_state"] == "uninterpreted_material"
    assert by_id["platform-authorization"]["output"]["catalog_retrieval_blocked"] is True

    assert by_id["research-plan"]["authority"] == "plans"
    assert by_id["research-trigger-observer"]["kind"] == "observer"
    assert by_id["research-trigger-observer"]["authority"] == "observes"
    assert by_id["research-trigger-observer"]["output"]["authoritative"] is False
    assert by_id["research-plan"]["status"] == "consent_required"
    assert by_id["buyer-research-consent"]["kind"] == "buyer_input"
    assert by_id["buyer-research-consent"]["authority"] == "grants_research_scope"
    assert by_id["buyer-research-consent"]["output"]["commercial_authority_granted"] is False
    assert by_id["semantic-evidence"]["kind"] == "connector"
    assert by_id["semantic-evidence"]["latency_ms"] == 12
    compiler = by_id["semantic-requirements-compiler"]
    assert compiler["kind"] == "gate"
    assert compiler["authority"] == "compiles_constraints"
    assert compiler["status"] == "accepted"
    assert compiler["output"]["compiled_requirements"]["ram_gb"]["value"] == 32
    assert by_id["semantic-authorization"]["kind"] == "gate"
    assert by_id["semantic-authorization"]["status"] == "blocked"
    assert by_id["material-clarification"]["authority"] == "requests_buyer_input"
    assert by_id["material-clarification"]["output"]["missing_slots"] == [
        "execution-location"
    ]
    assert by_id["material-clarification"]["output"]["commercial_authority_granted"] is False


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
def test_trace_scopes_catalog_policy_separately_from_workload_fit_authority():
    core = SimpleNamespace(
        lane="SEARCH",
        degraded=False,
        products=[SimpleNamespace()],
        clarify=[],
        extras={
            "decision": {"source": "model", "model_proposal": {}, "authorization_changes": []},
            "plan": {},
            "gates": {"policy_route": "allow", "source": "commerce_request_guard"},
            "qualification_authority": "none",
            "post_catalog_adjudication": {
                "qualification_authority": "none",
                "research_needed": True,
                "reason_codes": ["no_normalized_requirements"],
            },
            "stage_results": [],
        },
    )

    by_id = {item["id"]: item for item in build_execution_steps(core)}

    assert by_id["platform-authorization"]["authority_scope"] == "catalog_routing"
    assert by_id["commerce-policy-gate"]["authority_scope"] == "request_policy"
    assert by_id["post-catalog-adjudication"]["authority"] == "withholds_authority"
    assert by_id["buyer-response"]["label"] == "Present provisional catalog exploration"
