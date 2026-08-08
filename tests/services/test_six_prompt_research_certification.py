from src.app.services.six_prompt_research_certification import (
    SCENARIOS,
    certify_six_prompt_fixture,
)


def test_six_prompts_use_one_fixture_pipeline_and_produce_distinct_graphs() -> None:
    results = [certify_six_prompt_fixture(item.prompt) for item in SCENARIOS]

    assert len(results) == 6
    assert len({item.requirement_graph_hash for item in results}) == 6
    assert all(item.execution_mode == "deterministic_fixture" for item in results)
    assert all(item.paid_calls == 0 for item in results)
    assert all(item.external_calls == 0 for item in results)
    assert all(item.fixture_dispatches > 0 for item in results)
    assert all(all(receipt.fixture for receipt in item.receipts) for item in results)
    assert all(not receipt.network_execution for item in results for receipt in item.receipts)
    assert all(len(item.queries) >= 2 for item in results)
    assert all(item.architecture_alternatives for item in results)


def test_search_snippets_are_discovery_only_and_origins_establish_claims() -> None:
    result = certify_six_prompt_fixture(SCENARIOS[3].prompt)

    assert all("not accepted evidence" in row["content"] for response in result.searxng_responses for row in response["results"])
    assert result.accepted_claims
    assert all(claim.source_url.startswith("https://") for claim in result.accepted_claims)
    assert {receipt.capability for receipt in result.receipts} == {"WEB_DISCOVERY", "OFFICIAL_ORIGIN_FETCH"}


def test_predictive_twin_remains_honestly_unresolved_without_named_software() -> None:
    result = certify_six_prompt_fixture(SCENARIOS[0].prompt)

    assert "named local application" in result.unresolved[0]
    assert all(product.status == "conditional" for product in result.products)
    assert all(product.behavioural_performance == "not_verified" for product in result.products)


def test_cgi_and_unreal_do_not_invent_behavioral_performance() -> None:
    for scenario in (SCENARIOS[1], SCENARIOS[5]):
        result = certify_six_prompt_fixture(scenario.prompt)
        assert all(product.behavioural_performance == "not_verified" for product in result.products)
        assert all(claim.claim_class != "behavioural" for claim in result.accepted_claims)
        assert any(
            "not verified" in gap
            for product in result.products
            for gap in product.unknowns
        )


def test_expensive_high_spec_gaming_product_loses_cad_to_workstation() -> None:
    result = certify_six_prompt_fixture(SCENARIOS[2].prompt)
    by_sku = {product.sku: product for product in result.products}

    assert result.products[0].sku == "WS-MOBILE-01"
    assert by_sku["WS-MOBILE-01"].status == "qualified"
    assert by_sku["SCORP-126982"].status == "failed"
    assert "gpu_class" in by_sku["SCORP-126982"].misses
    assert by_sku["SCORP-126982"].price_cents > by_sku["WS-MOBILE-01"].price_cents


def test_ot_case_does_not_assume_isaac_or_local_physics() -> None:
    result = certify_six_prompt_fixture(SCENARIOS[3].prompt)
    serialized = result.model_dump_json().lower()

    assert "factory i/o" in serialized
    assert "isaac" not in serialized
    assert "physics" not in serialized
    assert "simultaneous vms" in result.material_question.lower()
