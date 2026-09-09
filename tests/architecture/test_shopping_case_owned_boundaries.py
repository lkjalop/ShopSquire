from src.app.routers import shopping_cases


def test_router_reexports_the_owned_contract_and_projection_boundaries():
    assert shopping_cases.ResearchShoppingCaseRequest.__module__ == 'src.app.schemas.shopping_case'
    assert shopping_cases._case_catalog_candidate_set_from_trace.__module__ == 'src.app.services.shopping_case_trace_reader'
    assert shopping_cases._catalog_shortfall_alternative.__module__ == 'src.app.services.catalog_shortfall_projection'
