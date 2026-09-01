from src.app.services.additive_workload_projection import catalog_authority_for_turn


def test_material_blocker_overrides_stale_permissive_semantic_authority() -> None:
    assert catalog_authority_for_turn(
        "permitted",
        material_blocked=True,
        has_products=True,
        requirements_established=True,
    ) == "blocked"


def test_resolved_requirements_and_products_establish_catalog_authority() -> None:
    assert catalog_authority_for_turn(
        "",
        material_blocked=False,
        has_products=True,
        requirements_established=True,
    ) == "permitted"
