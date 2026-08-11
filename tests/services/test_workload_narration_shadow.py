from src.app.services.recommendation_core.workload_narration_shadow import (
    run_shadow_narration,
    validate_shadow_narration,
)


DECISION = {
    "overall_decision": "conditional",
    "workload": {"material_unknowns": ["VM count"]},
    "fit_ledger": [{"attribute_label": "Host OS", "verdict": "unknown"}],
    "critic": {"status": "pass"},
    "authorized_narration_blocks": [],
}


def test_shadow_candidate_never_becomes_buyer_visible():
    result = run_shadow_narration(
        DECISION,
        generate=lambda _: (
            "Conditional. VM count and Host OS are still unresolved, and performance is not verified."
        ),
        model_id="test-model",
    )
    assert result["status"] == "accepted_shadow"
    assert result["buyer_visible"] is False
    assert result["commercial_authority_granted"] is False


def test_shadow_critic_gets_one_bounded_repair_without_gaining_authority():
    candidates = iter([
        "Conditional.",
        "Conditional. VM count and Host OS are still unresolved, and performance is not verified.",
    ])
    result = run_shadow_narration(DECISION, generate=lambda _: next(candidates), model_id="test")

    assert result["status"] == "accepted_shadow"
    assert result["generation_attempts"] == 2
    assert "material_unknowns_omitted" in result["initial_violations"]
    assert result["candidate_retained_for_audit"].startswith("Conditional")
    assert result["buyer_visible"] is False
    assert result["commercial_authority_granted"] is False


def test_shadow_guard_rejects_overstatement_and_invented_number():
    violations = validate_shadow_narration(
        "This is a good choice and will handle 70 models.", DECISION,
    )
    assert "decision_overstatement" in violations
    assert "material_unknowns_omitted" in violations
    assert "unreferenced_numeric_claim:70" in violations


def test_shadow_guard_rejects_unsourced_hardware_floor_even_when_number_is_observed():
    decision = {
        **DECISION,
        "fit_ledger": [{
            "attribute_key": "ram_gb", "attribute_label": "RAM",
            "required_text": "not recorded", "observed": 64,
            "observed_text": "64 GB", "verdict": "unknown",
            "requirement_claim_ids": [], "capability_claim_ids": ["cap-ram"],
        }],
    }
    violations = validate_shadow_narration(
        "You need at least 64 GB RAM; RAM is still unresolved.", decision,
    )
    assert "unsourced_hardware_floor:ram_gb" in violations


def test_shadow_guard_rejects_invented_behavioral_benchmark():
    decision = {
        **DECISION,
        "performance_status": "unknown",
        "fit_ledger": [{
            "attribute_key": "gpu", "attribute_label": "GPU",
            "verdict": "meets_minimum", "requirement_claim_ids": ["req-gpu"],
            "capability_claim_ids": ["cap-gpu"], "claim_class": "attested",
        }],
    }
    violations = validate_shadow_narration(
        "Performance is not verified, but expect a smooth benchmark result.", decision,
    )
    assert "behavioral_claim_without_exact_evidence" in violations


def test_shadow_guard_rejects_windows_pro_advice_without_requirement_reference():
    decision = {
        **DECISION,
        "fit_ledger": [{
            "attribute_key": "os_edition", "attribute_label": "Operating system",
            "required_text": "not recorded", "observed_text": "Windows 11 Home",
            "verdict": "unknown", "requirement_claim_ids": [],
            "capability_claim_ids": ["cap-os"],
        }],
    }
    violations = validate_shadow_narration(
        "Upgrade to Windows 11 Pro; the operating-system requirement is unresolved.", decision,
    )
    assert "windows_pro_advice_without_requirement_reference" in violations


def test_shadow_guard_rejects_great_for_workload_when_conditional():
    violations = validate_shadow_narration(
        "This laptop is great for the workload, although VM count is still unresolved.", DECISION,
    )
    assert "decision_overstatement" in violations


def test_shadow_guard_requires_budget_conflict_and_exact_ledger_gap_narration():
    decision = {
        **DECISION,
        "budget_status": "over",
        "fit_ledger": [
            {"attribute_key": "os_edition", "attribute_label": "Host OS edition", "verdict": "unknown"},
            {"attribute_key": "gpu_tgp_w", "attribute_label": "GPU power limit", "verdict": "contested"},
        ],
    }
    violations = validate_shadow_narration(
        "Some specifications are unresolved.", decision,
    )
    assert "budget_conflict_omitted" in violations
    assert "ledger_gap_omitted:os_edition" in violations
    assert "ledger_gap_omitted:gpu_tgp_w" in violations

    accepted = validate_shadow_narration(
        "This is over the budget ceiling. Host OS edition and GPU power limit remain unresolved; "
        "behavioral performance is not verified.",
        decision,
    )
    assert accepted == []


def test_shadow_guard_allows_sourced_hardware_floor_and_windows_pro_requirement():
    decision = {
        "overall_decision": "qualified_for_stated_scope",
        "budget_status": "within",
        "performance_status": "unknown",
        "workload": {"material_unknowns": []},
        "fit_ledger": [
            {
                "attribute_key": "ram_gb", "attribute_label": "RAM",
                "required_text": ">= 64 GB", "observed": 64, "observed_text": "64 GB",
                "verdict": "meets_minimum", "requirement_claim_ids": ["req-ram"],
                "capability_claim_ids": ["cap-ram"],
            },
            {
                "attribute_key": "os_edition", "attribute_label": "Operating system",
                "required_text": "Windows 11 Pro", "observed_text": "Windows 11 Pro",
                "verdict": "meets_minimum", "requirement_claim_ids": ["req-os"],
                "capability_claim_ids": ["cap-os"],
            },
        ],
        "critic": {"status": "pass"},
        "authorized_narration_blocks": [],
    }
    assert validate_shadow_narration(
        "The accepted minimum is 64 GB RAM. Use Windows 11 Pro. "
        "Behavioral performance is not verified.",
        decision,
    ) == []
