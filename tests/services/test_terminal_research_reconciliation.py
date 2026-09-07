from src.app.services.terminal_research_reconciliation import (
    gate_terminal_catalog_projection,
    reconcile_semantic_resolution,
)


def _semantic(*, extra_concept: bool = False) -> dict:
    concepts = [{
        "text": "pragmata",
        "query_span": "pragmata",
        "status": "unresolved",
        "material": True,
    }]
    unknowns = [{
        "unknown_id": "purpose-1",
        "description": "Authoritative meaning and requirements for pragmata",
        "resolution_source": "research",
        "material": True,
    }]
    if extra_concept:
        concepts.append({
            "text": "local VR headset compatibility",
            "query_span": "VR headset",
            "status": "unresolved",
            "material": True,
        })
        unknowns.append({
            "unknown_id": "compatibility-2",
            "description": "Which VR headset must be supported",
            "resolution_source": "buyer",
            "material": True,
        })
    return {
        "outcome": "clarify",
        "catalog_authority": "blocked",
        "reasons": ["unresolved_material_concept"],
        "concepts": concepts,
        "material_unknowns": unknowns,
        "questions": [{"question_id": "workload_architecture", "material": True}],
        "state_prevented": ["catalog_recommendation", "commerce_execution"],
        "next_permitted_action": "ask_material_clarification",
        "residual_route": "ASK",
        "residual_reasons": ["material_buyer_input_required"],
        "authorization_granted": False,
    }


def _authorization() -> dict:
    return {
        "status": "resolved",
        "reason": "enrolled_structured_provider_requirements",
        "evidence": [{
            "requested_name": "pragmata",
            "canonical_title": "PRAGMATA",
            "app_id": "3357650",
            "status": "resolved",
            "source_url": "https://store.steampowered.com/app/3357650/",
            "compiled_requirements": [
                {"attribute_key": "ram_gb", "operator": ">=", "value": 16},
            ],
        }],
    }


def test_provider_resolution_clears_only_the_bound_material_concept() -> None:
    result = reconcile_semantic_resolution(_semantic(), _authorization())

    assert result.resolved_concept_spans == ("pragmata",)
    assert result.requirements_established is True
    assert result.semantic_resolution["outcome"] == "proceed_catalog"
    assert result.semantic_resolution["catalog_authority"] == "permitted"
    assert result.semantic_resolution["concepts"][0]["status"] == "resolved"
    assert result.semantic_resolution["material_unknowns"][0]["status"] == "resolved"
    assert result.semantic_resolution["questions"] == []


def test_provider_resolution_does_not_clear_an_unrelated_material_unknown() -> None:
    result = reconcile_semantic_resolution(
        _semantic(extra_concept=True), _authorization(),
    )

    assert result.semantic_resolution["outcome"] == "clarify"
    assert result.semantic_resolution["catalog_authority"] == "blocked"
    assert result.semantic_resolution["concepts"][0]["status"] == "resolved"
    assert result.semantic_resolution["concepts"][1]["status"] == "unresolved"
    assert result.semantic_resolution["material_unknowns"][1].get("status") != "resolved"


def test_unbound_provider_evidence_cannot_release_catalog_authority() -> None:
    authorization = _authorization()
    authorization["evidence"][0]["requested_name"] = "a different title"

    result = reconcile_semantic_resolution(_semantic(), authorization)

    assert result.resolved_concept_spans == ()
    assert result.semantic_resolution["catalog_authority"] == "blocked"


def test_provider_identity_binds_when_concept_span_also_contains_performance_target() -> None:
    semantic = _semantic()
    semantic["concepts"][0].update({
        "text": "PRAGMATA at 1080p",
        "query_span": "PRAGMATA at 1080p",
    })
    semantic["material_unknowns"][0]["description"] = (
        "Authoritative meaning and requirements for PRAGMATA at 1080p"
    )

    result = reconcile_semantic_resolution(semantic, _authorization())

    assert result.resolved_concept_spans == ("pragmata",)
    assert result.requirements_established is True
    assert result.semantic_resolution["catalog_authority"] == "permitted"


def test_identity_confirmation_clears_pre_research_catalog_projection() -> None:
    result = gate_terminal_catalog_projection(
        research_status="identity_confirmation_required",
        products=[{"sku": "STALE-1"}],
        product_shelves={"shelves": [{"initial": [{"sku": "STALE-1"}]}]},
        catalog_authority="provisional",
    )

    assert result.products == ()
    assert result.product_shelves is None
    assert result.catalog_authority == "blocked"


def test_resolved_research_preserves_catalog_projection() -> None:
    result = gate_terminal_catalog_projection(
        research_status="requirements_resolved",
        products=[{"sku": "FIT-1"}],
        product_shelves={"shelves": [{"initial": [{"sku": "FIT-1"}]}]},
        catalog_authority="permitted",
    )

    assert result.products == ({"sku": "FIT-1"},)
    assert result.product_shelves is not None
    assert result.catalog_authority == "permitted"
    assert result.recommendation_status == "qualified"


def test_blocked_authority_cannot_be_overridden_by_populated_shelves() -> None:
    result = gate_terminal_catalog_projection(
        research_status="requirements_resolved",
        products=[{"sku": "UNQUALIFIED"}],
        product_shelves={"shelves": [{"initial": [{"sku": "UNQUALIFIED"}]}]},
        catalog_authority="blocked",
    )
    assert result.products == ()
    assert result.product_shelves is None
    assert result.recommendation_status == "blocked"


def test_provisional_and_unknown_candidates_are_not_qualified() -> None:
    for authority in ("provisional", "unknown", None):
        result = gate_terminal_catalog_projection(
            research_status="claims_pending_policy_review",
            products=[{"sku": "EXPLORATION"}], product_shelves=None,
            catalog_authority=authority,
        )
        assert result.recommendation_status == "held"


def test_permitted_authority_without_matches_is_not_a_qualified_result() -> None:
    result = gate_terminal_catalog_projection(
        research_status="requirements_resolved", products=[], product_shelves=None,
        catalog_authority="permitted",
    )
    assert result.recommendation_status == "no_qualified_products"


def test_structured_provider_recovers_router_empty_semantics_from_literal_buyer_identity() -> None:
    result = reconcile_semantic_resolution(
        {"catalog_authority": "blocked", "concepts": [], "material_unknowns": []},
        _authorization(),
        buyer_text="What laptop can run PRAGMATA at 1080p?",
    )

    assert result.requirements_established is True
    assert result.resolved_concept_spans == ("pragmata",)
    assert result.semantic_resolution["catalog_authority"] == "permitted"


def test_structured_provider_cannot_recover_empty_semantics_for_unrelated_buyer_text() -> None:
    result = reconcile_semantic_resolution(
        {"catalog_authority": "blocked", "concepts": [], "material_unknowns": []},
        _authorization(),
        buyer_text="What laptop can run a different title?",
    )

    assert result.requirements_established is False
    assert result.semantic_resolution["catalog_authority"] == "blocked"
