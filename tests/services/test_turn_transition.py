from src.app.services.turn_transition import (
    TurnCommit,
    TurnTransition,
    build_turn_read_model,
    derive_turn_transition,
)


def test_transition_priority_is_explicit_and_bounded():
    assert derive_turn_transition(active_case=True, new_category=True) == TurnTransition.NEW_CATEGORY
    assert derive_turn_transition(
        active_case=True, additive_workload=True, subject_action="continue",
    ) == TurnTransition.ADD_WORKLOAD
    assert derive_turn_transition(
        active_case=True, additive_workload=True, subject_action="switch",
    ) == TurnTransition.ADD_WORKLOAD
    assert derive_turn_transition(
        active_case=True, pending_clarification={"question_id": "locality"},
        clarification_relation="answer",
    ) == TurnTransition.ANSWER_PENDING
    assert derive_turn_transition(
        active_case=True, commercial_amendment=True,
    ) == TurnTransition.COMMERCIAL_AMENDMENT
    assert derive_turn_transition(
        active_case=True, workload_refinement=True,
    ) == TurnTransition.REFINE_WORKLOAD
    assert derive_turn_transition(active_case=False) == TurnTransition.UNRESOLVED


def test_revision_bound_read_model_is_a_projection_of_one_commit():
    commit = TurnCommit(
        case_id="sc-demo",
        expected_revision=4,
        source_message_id="msg-1",
        idempotency_key="idem-1",
        transition=TurnTransition.ADD_WORKLOAD,
        objective="Gaming plus Emulate3D",
        buyer_query="Actually I need a chair instead",
        workloads=["Baldur's Gate 3", "Rockwell Emulate3D"],
        preserved_fields=["budget"],
        canonical_budget={"budget_min": None, "budget_max": 3000, "mode": "ceiling", "source_span": [0, 8]},
        commercial_terms={"currency": "AUD", "budget_scope": "unknown"},
        subject_role="RUN_SUBJECT_ON_PRODUCT",
        pending_clarification={"action": "consume", "prior_question_id": "locality"},
        external_research_authorized=True,
        operation_id="chat:idem-1",
        research={
            "source_resolution": {
                "source_intake_certificate": {
                    "resolution": {"status": "resolved"},
                    "security": {"status": "observed_untrusted_content_pending_compilation"},
                    "execution": {"origin_fetch_status": "completed"},
                    "claim_compilation": {
                        "status": "claims_pending_policy_review",
                        "accepted": 0,
                        "provisional": 9,
                        "rejected": 0,
                    },
                },
            },
        },
        catalog_scope={
            "schema_version": "catalog-scope-v1",
            "tenant_id": "default",
            "allowed_taxonomy_roots": ["el-6-6"],
            "selected_taxonomy_root": "el-6-6",
            "source": "tenant_primary",
            "confidence": 0.9,
            "client_context_disposition": "not_supplied",
            "reason": "tenant_grounded_primary_category",
        },
        catalog_authority="blocked",
        assistant_message="I retained the budget and added Emulate3D.",
    )
    projection = build_turn_read_model(commit, revision=5)
    assert projection.case_revision == 5
    assert projection.buyer_query == "Actually I need a chair instead"
    assert projection.objective == "Gaming plus Emulate3D"
    assert projection.transition == TurnTransition.ADD_WORKLOAD
    assert projection.pending_clarification.action == "consume"
    assert projection.catalog_authority == "blocked"
    assert projection.commerce_authority == "none"
    assert projection.research_outcome.case_revision == 5
    assert projection.research_outcome.operation_id == "chat:idem-1"
    assert projection.research_outcome.held_claim_count == 9
    assert projection.canonical_budget == {
        "budget_min": None, "budget_max": 3000, "mode": "ceiling", "source_span": [0, 8],
    }
    assert projection.subject_role == "RUN_SUBJECT_ON_PRODUCT"
    assert projection.operation_id == "chat:idem-1"
    assert projection.right_panel["canonical_budget"] == projection.canonical_budget
    assert projection.right_panel["commercial_terms"] == projection.commercial_terms
    assert projection.right_panel["subject_role"] == projection.subject_role
    assert projection.catalog_scope["selected_taxonomy_root"] == "el-6-6"
    assert projection.right_panel["catalog_scope"] == projection.catalog_scope
    assert projection.catalog_scope["case_id"] == "sc-demo"
    assert projection.catalog_scope["case_revision"] == 5
    assert "case_revision" not in commit.catalog_scope


def test_effective_quantity_keeps_literal_provenance_and_uses_committed_state():
    from src.app.services.turn_transition import effective_turn_facts
    result=effective_turn_facts({'quantity':20,'commercial_terms':{'quantity':20}},
        canonical_budget=None,canonical_quantity=12)
    assert result['quantity']==result['commercial_terms']['quantity']==12
    assert result['literal_quantity']==20
    assert result['quantity_source']=='accepted_case_constraints'


def test_effective_budget_scope_and_currency_follow_committed_case():
    from src.app.services.turn_transition import effective_turn_facts
    result=effective_turn_facts({'budget_scope':'unknown','commercial_terms':{'currency':'USD','budget_scope':'unknown'}},
        canonical_budget={'budget_max':2000},canonical_quantity=3,
        accepted_budget={'amount_minor':200000,'currency':'AUD','scope':'per_unit'})
    assert result['budget_scope']==result['commercial_terms']['budget_scope']=='per_unit'
    assert result['commercial_terms']['currency']=='AUD'
    assert result['literal_commercial_terms']=={'currency':'USD','budget_scope':'unknown'}


def test_partial_requirements_replace_stale_read_model_fit_narration():
    commit = TurnCommit(
        case_id="partial", expected_revision=1, source_message_id="m", idempotency_key="i",
        transition=TurnTransition.REFINE_WORKLOAD, catalog_authority="permitted",
        assistant_message="This computer fully qualifies.", products=[{"sku": "ram-only"}],
        research={"workload_authorization": {"evidence": [{
            "compiled_requirements": [{"attribute_key": "ram_gb", "value": 8}],
            "claim_rejections": [{"attribute_key": "cpu_model"}],
        }]}},
    )
    result = build_turn_read_model(commit, revision=2)
    assert result.catalog_authority == result.research_outcome.catalog_authority == "blocked"
    assert result.products == []
    assert "fully qualifies" not in result.assistant_message
    assert "partial" in result.assistant_message


def test_committed_read_model_includes_execution_failure_and_retained_facts():
    commit = TurnCommit(
        case_id="sc-owned", expected_revision=1, source_message_id="m", idempotency_key="i",
        transition=TurnTransition.REFINE_WORKLOAD, catalog_authority="blocked",
        execution_evidence={"failure_code": "model_execution_unavailable"},
        assistant_message="May I research official requirements?",
    )
    result = build_turn_read_model(commit, revision=2, canonical_state={
        "case_id": "sc-owned", "revision": 2, "requested_quantity": 40,
    })
    assert result.assistant_message.startswith("Your retained request: 40 units.")
    assert "unavailable" in result.assistant_message.lower()
    assert result.right_panel["retained_buyer_facts"] == {"requested_quantity": 40}
