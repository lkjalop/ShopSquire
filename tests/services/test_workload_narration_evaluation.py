import json

from src.app.services.recommendation_core.workload_narration_evaluation import (
    build_shadow_evaluation_corpus,
    evaluate_shadow_corpus,
)


def _authorized_blocks(prompt: str) -> str:
    decision = json.loads(prompt.split("DECISION_JSON:\n", 1)[1])
    return " ".join(decision["authorized_narration_blocks"])


def test_corpus_covers_six_prompts_and_material_commercial_edges() -> None:
    corpus = build_shadow_evaluation_corpus()
    categories = [row["category"] for row in corpus]
    assert len(corpus) == 10
    assert categories.count("research_prompt") == 6
    assert set(categories) >= {
        "uploaded_requirements", "budget_conflict", "exact_product_gaps",
        "supplier_choice",
    }


def test_authorized_blocks_pass_with_zero_unsupported_or_omitted_material_facts() -> None:
    report = evaluate_shadow_corpus(
        generate=_authorized_blocks,
        model_id="deterministic-authorized-block-replay",
    )
    assert report["case_count"] == 10
    assert report["unsupported_claim_count"] == 0
    assert report["preservation_failure_count"] == 0
    assert report["fidelity_passed"] is True
    assert report["buyer_visible"] is False
    assert report["commercial_authority_granted"] is False
    assert all(row["rollout"]["buyer_visible"] is False for row in report["results"])
    assert all(
        row["rollout"]["buyer_renderer"] == "deterministic_authorized_blocks"
        for row in report["results"]
    )


def test_omitted_gaps_budget_and_supplier_choices_fail_fidelity() -> None:
    corpus = tuple(
        row for row in build_shadow_evaluation_corpus()
        if row["category"] in {"budget_conflict", "exact_product_gaps", "supplier_choice"}
    )
    report = evaluate_shadow_corpus(
        corpus=corpus,
        generate=lambda _: "This option remains conditional.",
        model_id="omission-probe",
    )
    assert report["fidelity_passed"] is False
    assert report["preservation_failure_count"] > 0
    flattened = {
        violation
        for row in report["results"]
        for violation in row["preservation_failures"]
    }
    assert "budget_conflict_omitted" in flattened
    assert any("identity-gaps" in value for value in flattened)
    assert any("supplier-choices" in value for value in flattened)


def test_hallucinated_number_is_counted_as_an_unsupported_claim() -> None:
    corpus = (build_shadow_evaluation_corpus()[0],)
    report = evaluate_shadow_corpus(
        corpus=corpus,
        generate=lambda prompt: _authorized_blocks(prompt) + " It will achieve 777 FPS.",
        model_id="hallucination-probe",
    )
    assert report["fidelity_passed"] is False
    assert report["unsupported_claim_count"] >= 2
    violations = report["results"][0]["unsupported_claim_violations"]
    assert "unreferenced_numeric_claim:777" in violations
    assert "behavioral_claim_without_exact_evidence" in violations


def test_latency_is_reported_as_observation_not_fidelity_certification() -> None:
    report = evaluate_shadow_corpus(
        corpus=(build_shadow_evaluation_corpus()[0],),
        generate=_authorized_blocks,
        model_id="latency-contract-probe",
    )
    assert report["latency_observation"]["certification_status"] == (
        "observed_separately_not_a_fidelity_gate"
    )
