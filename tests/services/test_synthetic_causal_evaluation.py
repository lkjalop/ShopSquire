from __future__ import annotations

from src.app.services.synthetic_causal_evaluation import (
    evaluate_scenario_cohorts,
)


def test_multiseed_cohorts_are_deterministic_and_permanently_simulated():
    kwargs = {
        "scenario_ids": [
            "intermittent_critical_spare",
            "perishable_cold_chain",
        ],
        "seeds": [7, 13],
        "days": 120,
        "cohort_dimensions": {
            "intermittent_critical_spare": {
                "archetype": "critical_spare",
                "lifecycle_stage": "mature",
            },
            "perishable_cold_chain": {
                "archetype": "shelf_life_constrained",
                "lifecycle_stage": "mature",
            },
        },
    }

    first = evaluate_scenario_cohorts(**kwargs)
    second = evaluate_scenario_cohorts(**kwargs)

    assert first == second
    assert first["manifest"]["run_count"] == 4
    assert first["manifest"]["seeds"] == [7, 13]
    assert first["authority"] == "simulation_only"
    assert first["execution_allowed"] is False
    assert first["can_increase_autonomy"] is False
    assert all(run["authority"] == "simulation_only" for run in first["runs"])
    assert all(run["execution_allowed"] is False for run in first["runs"])


def test_evaluation_separates_truth_observation_publication_and_availability():
    report = evaluate_scenario_cohorts(
        scenario_ids=["electronics_memory_allocation"],
        seeds=[5],
        days=260,
        include_adversarial=True,
    )
    run = report["runs"][0]

    assert run["latent_truth"]["shock"]["occurred_at"]
    evidence = run["observed_evidence"]
    assert evidence
    assert all(item["observed_at"] for item in evidence)
    assert all(item["published_at"] for item in evidence)
    assert all(item["available_at"] for item in evidence)
    assert all(
        item["observed_at"] <= item["published_at"] <= item["available_at"]
        for item in evidence
    )
    assert {
        "misleading_correlation",
        "contradictory_supplier_claim",
    } <= {item["adversarial_kind"] for item in evidence if item["adversarial"]}
    assert all(item["authority"] == "simulation_only" for item in evidence)


def test_conditional_coverage_has_explicit_dimensions_and_undefined_states():
    report = evaluate_scenario_cohorts(
        scenario_ids=["intermittent_critical_spare"],
        seeds=[2, 3],
        days=50,
    )

    coverage = report["conditional_interval_coverage"]
    assert set(coverage) == {
        "archetype",
        "lifecycle_stage",
        "intermittency",
        "lead_time_regime",
        "disruption",
    }
    lifecycle = coverage["lifecycle_stage"]["undefined_not_declared"]
    assert lifecycle["status"].startswith("undefined_")
    assert lifecycle["empirical_coverage"] is None
    assert set(lifecycle["by_model"]) <= {
        "seasonal_naive",
        "ewma",
        "croston_sba",
        "tsb",
    }
    assert coverage["intermittency"]


def test_policy_aggregation_reports_requested_business_outcomes_honestly():
    report = evaluate_scenario_cohorts(
        scenario_ids=["packaging_resin_freight"],
        seeds=[11, 12, 13],
        days=220,
    )

    policy = report["policy_counterfactuals"]
    assert policy["status"] in {"observed", "partially_observed"}
    assert {
        "fill_rate",
        "stockout_units",
        "waste_units",
        "gross_margin_minor",
        "working_capital_minor",
        "service_impact",
    } <= set(policy["metrics"])
    assert policy["metrics"]["waste_units"]["status"] == "observed"
    assert policy["metrics"]["waste_units"]["candidate_mean"] is not None
    assert policy["metrics"]["fill_rate"]["status"] == "observed"
    assert policy["limitations"]
    assert policy["causal_claim_allowed"] is False
