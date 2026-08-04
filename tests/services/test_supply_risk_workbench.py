from src.app.services.supply_risk_workbench import (
    build_supply_risk_workbench,
    list_supply_risk_scenarios,
)


def test_scenario_catalog_contains_missing_archetypes_and_pestel_scope():
    scenarios = {
        row["scenario_id"]: row for row in list_supply_risk_scenarios()
    }
    assert {
        "intermittent_critical_spare",
        "perishable_cold_chain",
        "bulky_freight_exposure",
        "b2b_project_item",
    } <= set(scenarios)
    assert scenarios["perishable_cold_chain"]["pestel_domains"]
    assert all(row["authority"] == "simulation_only" for row in scenarios.values())


def test_workbench_is_tenant_scoped_grounded_and_non_executable():
    result = build_supply_risk_workbench(
        tenant_id="tenant-a",
        scenario_id="electronics_memory_allocation",
        seed=42,
        days=400,
        decision_time="2026-07-29T00:00:00Z",
    )
    assert result["tenant_id"] == "tenant-a"
    assert result["authority"] == "simulation_only"
    assert result["execution_allowed"] is False
    assert result["dependency_paths"]
    assert result["impact"]["landed_cost_change_pct"]["high"] > 0
    assert result["pestel_domains"] == ["economic", "technological"]
    assert result["alternatives"]
    assert result["procurement_options"]["execution_allowed"] is False
    assert result["contradictions"]["winner"] is None
    assert "policy" in result["contradictions"]
    assert result["signals"][0]["freshness"]["status"] == "simulated"
    candidates = result["signals"][0]["official_source_candidates"]
    assert candidates == []  # capacity evidence needs a declared source adapter
    assert "registered_official_source_for_signal_type" in (
        result["completeness"]["missing_evidence"]
    )
