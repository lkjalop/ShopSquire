from __future__ import annotations

from src.app.services.market_source_registry import (
    govern_external_observation,
    load_market_source_registry,
    sources_for_signal,
)
from src.app.services.market_evidence_policy import resolve_contradictions
from src.app.services.synthetic_supply_history import (
    generate_commerce_history,
    generate_supply_scenario,
)
from src.app.services.supply_impact_reasoner import (
    build_grounded_impact_hypothesis,
    propose_procurement_options,
)


def test_external_source_registry_is_explicitly_licensed_and_scoped():
    registry = load_market_source_registry()
    assert {"world_bank_pink_sheet", "usgs_minerals", "usda_wasde", "eia_fuels"} <= set(
        registry
    )
    for source in registry.values():
        assert source["trust_tier"] in {"T1", "T2", "T3", "T4"}
        assert source["licence_url"]
        assert source["permitted_uses"]
        assert source["measurement_scope"]
        assert source["pestel_domains"]
        assert set(source["pestel_domains"]) <= {
            "political",
            "economic",
            "social",
            "technological",
            "environmental",
            "legal",
        }
        assert source["decision_authority"] == "advisory_only"
        assert source["personal_data_allowed"] is False

    fuel = sources_for_signal("transport_fuel_price")
    assert [row["source_id"] for row in fuel] == ["eia_fuels", "world_bank_pink_sheet"]


def test_external_observation_preserves_release_time_scope_and_advisory_authority():
    governed = govern_external_observation(
        source_id="usgs_minerals",
        source_record_id="mcs-2026-gallium",
        signal_type="mineral_supply_concentration",
        subject_id="material:gallium",
        measurement={"kind": "net_import_reliance", "value": 100, "unit": "percent"},
        geography="US",
        effective_from="2025-01-01T00:00:00Z",
        effective_to="2025-12-31T23:59:59Z",
        published_at="2026-02-06T00:00:00Z",
        available_at="2026-02-06T00:00:00Z",
        retrieved_at="2026-07-29T00:00:00Z",
    )
    assert governed["authority"] == "advisory_only"
    assert governed["measurement"]["kind"] == "net_import_reliance"
    assert governed["geography"] == "US"
    assert governed["effective_from"].startswith("2025-")
    assert governed["published_at"].startswith("2026-")
    assert governed["provenance_chain"][-1] == "record/mcs-2026-gallium"
    assert governed["source_policy"]["measurement_scope"]


def test_contradictions_with_different_scope_are_not_collapsed_to_one_winner():
    common_policy = {
        "source_system": "official",
        "trust_tier": "T2",
        "licence_id": "open",
        "licence_url": "https://example.test/terms",
        "retrieved_at": "2026-07-29T00:00:00Z",
        "terms_hash": "a" * 64,
        "allowed_uses": ["advisory"],
        "approved_by": "operator",
    }
    result = resolve_contradictions([
        {
            "id": "au",
            "direction": "up",
            "geography": "AU",
            "measurement_definition": "supplier_quote_index",
            "observed_at": "2026-07-28T00:00:00Z",
            "confidence": 0.9,
            "provenance_chain": ["official/au"],
            "source_policy": common_policy,
        },
        {
            "id": "us",
            "direction": "down",
            "geography": "US",
            "measurement_definition": "supplier_quote_index",
            "observed_at": "2026-07-28T00:00:00Z",
            "confidence": 0.9,
            "provenance_chain": ["official/us"],
            "source_policy": common_policy,
        },
    ])
    assert result["status"] == "incomparable_scopes"
    assert result["winner"] is None
    assert result["contested"] is True
    assert set(result["scope_groups"]) == {
        "AU|supplier_quote_index||",
        "US|supplier_quote_index||",
    }


def test_synthetic_supply_scenario_is_deterministic_and_never_authoritative():
    first = generate_supply_scenario("electronics_memory_allocation", seed=42)
    second = generate_supply_scenario("electronics_memory_allocation", seed=42)
    assert first == second
    shorter = generate_commerce_history(
        "electronics_memory_allocation",
        seed=42,
        days=399,
    )
    assert shorter["manifest"]["parameter_hash"] != first["manifest"]["parameter_hash"]
    assert first["manifest"]["parameter_hash"]
    assert first["manifest"]["authority"] == "simulation_only"
    assert all(node["simulation_only"] for node in first["nodes"])
    assert all(edge["simulation_only"] for edge in first["edges"])
    assert all(signal["status"] == "simulated" for signal in first["signals"])
    assert all(signal["pestel_domains"] for signal in first["signals"])


def test_synthetic_commerce_history_is_replayable_conserved_and_censored():
    first = generate_commerce_history(
        "electronics_memory_allocation",
        seed=42,
        days=400,
    )
    second = generate_commerce_history(
        "electronics_memory_allocation",
        seed=42,
        days=400,
    )
    assert first == second
    assert first["manifest"]["authority"] == "simulation_only"
    assert first["manifest"]["evidence_availability_clock"] == "event_time"
    assert len(first["daily_history"]) == 400
    assert first["summary"]["stockout_days"] > 0
    assert first["summary"]["lost_sales_units"] > 0

    for day in first["daily_history"]:
        assert day["observed_sales_units"] <= day["latent_demand_units"]
        assert day["lost_sales_units"] == (
            day["latent_demand_units"] - day["observed_sales_units"]
        )
        assert day["closing_on_hand_units"] == (
            day["opening_on_hand_units"]
            + day["receipt_units"]
            - day["observed_sales_units"]
        )
        assert day["simulation_only"] is True

    before = [
        po for po in first["purchase_orders"]
        if po["order_day"] < first["manifest"]["shock_day"]
    ]
    after = [
        po for po in first["purchase_orders"]
        if po["order_day"] >= first["manifest"]["shock_day"]
    ]
    assert before and after
    assert min(po["unit_cost_minor"] for po in after) > max(
        po["unit_cost_minor"] for po in before
    )
    assert (
        sum(po["planned_lead_time_days"] for po in after) / len(after)
        > sum(po["planned_lead_time_days"] for po in before) / len(before)
    )


def test_grounded_impact_requires_dependency_path_and_preserves_uncertainty():
    scenario = generate_supply_scenario("electronics_memory_allocation", seed=17)
    hypothesis = build_grounded_impact_hypothesis(
        tenant_id="synthetic-lab",
        target_node_id="variant:portable-compute-a",
        nodes=scenario["nodes"],
        edges=scenario["edges"],
        signals=scenario["signals"],
        decision_time="2026-07-29T00:00:00Z",
    )
    assert hypothesis["status"] == "supported_hypothesis"
    assert hypothesis["causal_language"] == "consistent_with"
    assert hypothesis["dependency_paths"]
    assert hypothesis["impact"]["landed_cost_change_pct"]["low"] >= 0
    assert hypothesis["impact"]["landed_cost_change_pct"]["high"] > 0
    assert hypothesis["alternatives"]
    assert hypothesis["missing_evidence"]
    assert hypothesis["authority"] == "advisory_only"
    assert hypothesis["execution_allowed"] is False

    unrelated = build_grounded_impact_hypothesis(
        tenant_id="synthetic-lab",
        target_node_id="variant:unrelated",
        nodes=scenario["nodes"] + [{
            "id": "variant:unrelated", "node_type": "finished_variant",
            "label": "Unrelated variant", "simulation_only": True,
        }],
        edges=scenario["edges"],
        signals=scenario["signals"],
        decision_time="2026-07-29T00:00:00Z",
    )
    assert unrelated["status"] == "no_verified_exposure"
    assert unrelated["impact"] is None


def test_confirmed_supplier_evidence_can_strengthen_but_not_authorize_causality():
    scenario = generate_supply_scenario("packaging_resin_freight", seed=9)
    scenario["signals"].append({
        "id": "signal:supplier-confirmation",
        "subject_node_id": "supplier:packaging-a",
        "signal_type": "supplier_confirmation",
        "direction": "up",
        "magnitude_low_pct": 7.0,
        "magnitude_high_pct": 7.0,
        "confidence": 1.0,
        "status": "observed",
        "source_system": "supplier_quote",
        "source_record_id": "quote-confirmation-1",
        "provenance_chain": ["supplier_quote/quote-confirmation-1"],
        "available_at": "2026-07-25T00:00:00Z",
        "simulation_only": True,
        "confirms_signal_ids": ["signal:resin-price"],
    })
    hypothesis = build_grounded_impact_hypothesis(
        tenant_id="synthetic-lab",
        target_node_id="variant:packaged-consumable-a",
        nodes=scenario["nodes"],
        edges=scenario["edges"],
        signals=scenario["signals"],
        decision_time="2026-07-29T00:00:00Z",
    )
    assert hypothesis["causal_language"] == "supplier_confirmed_exposure"
    assert hypothesis["authority"] == "advisory_only"
    assert hypothesis["execution_allowed"] is False


def test_procurement_options_are_bounded_proposals_with_tradeoffs():
    scenario = generate_supply_scenario("seasonal_fibre_capacity", seed=7)
    hypothesis = build_grounded_impact_hypothesis(
        tenant_id="synthetic-lab",
        target_node_id="variant:seasonal-softgoods-a",
        nodes=scenario["nodes"],
        edges=scenario["edges"],
        signals=scenario["signals"],
        decision_time="2026-07-29T00:00:00Z",
    )
    proposal = propose_procurement_options(hypothesis)
    assert proposal["authority"] == "proposal_only"
    assert proposal["execution_allowed"] is False
    assert proposal["human_approval_required"] is True
    assert {"request_supplier_confirmation", "source_qualified_alternative", "monitor"} <= {
        option["action_type"] for option in proposal["options"]
    }
    assert all(option["tradeoffs"] for option in proposal["options"])
