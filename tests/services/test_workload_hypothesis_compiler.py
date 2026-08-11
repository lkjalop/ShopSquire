import pytest
from pydantic import ValidationError

from src.app.services.recommendation_core.research_contracts import CompiledRequirement
from src.app.services.recommendation_core.workload_hypothesis_compiler import (
    HypothesisProposal,
    HypothesisSetProposal,
    QuestionCandidate,
    compile_workload_hypotheses,
)


def _requirement(
    attribute_key: str,
    value: int | str | bool,
    claim_id: str,
    *,
    operator: str = ">=",
    unit: str | None = None,
) -> CompiledRequirement:
    return CompiledRequirement(
        attribute_key=attribute_key,
        operator=operator,
        value=value,
        unit=unit,
        source_claim_ids=[claim_id],
    )


def test_compiler_limits_model_proposal_to_one_through_three_hypotheses():
    with pytest.raises(ValidationError):
        HypothesisSetProposal(hypotheses=[])

    with pytest.raises(ValidationError):
        HypothesisSetProposal(
            hypotheses=[
                HypothesisProposal(
                    hypothesis_id=f"h{index}",
                    label=f"Hypothesis {index}",
                    requirement_claim_ids=[f"claim-{index}"],
                )
                for index in range(4)
            ]
        )


def test_shared_floor_contains_only_identical_grounded_requirements():
    proposal = HypothesisSetProposal(
        hypotheses=[
            HypothesisProposal(
                hypothesis_id="local-vm",
                label="Local virtual machines",
                requirement_claim_ids=["vm-ram", "vm-storage"],
            ),
            HypothesisProposal(
                hypothesis_id="local-visual",
                label="Local visual simulation",
                requirement_claim_ids=["visual-ram", "visual-storage", "visual-vram"],
            ),
        ]
    )
    result = compile_workload_hypotheses(
        proposal,
        compiled_requirements=[
            _requirement("ram_gb", 32, "vm-ram", unit="GB"),
            _requirement("storage_gb", 1024, "vm-storage", unit="GB"),
            _requirement("ram_gb", 32, "visual-ram", unit="GB"),
            _requirement("storage_gb", 1024, "visual-storage", unit="GB"),
            _requirement("gpu_vram_gb", 16, "visual-vram", unit="GB"),
        ],
    )

    assert [item.attribute_key for item in result.shared_requirements] == [
        "ram_gb",
        "storage_gb",
    ]
    assert result.shared_requirements[0].source_claim_ids == ["visual-ram", "vm-ram"]
    assert [axis.attribute_key for axis in result.divergent_axes] == ["gpu_vram_gb"]
    assert result.divergent_axes[0].variants["local-vm"] == []
    assert result.divergent_axes[0].variants["local-visual"][0].value == 16


def test_unknown_and_unreferenced_requirements_never_enter_shared_floor():
    proposal = HypothesisSetProposal(
        hypotheses=[
            HypothesisProposal(
                hypothesis_id="one",
                label="First interpretation",
                requirement_claim_ids=["ram-one", "invented-vram"],
            ),
            HypothesisProposal(
                hypothesis_id="two",
                label="Second interpretation",
                requirement_claim_ids=["ram-two", "invented-vram"],
            ),
        ]
    )
    result = compile_workload_hypotheses(
        proposal,
        compiled_requirements=[
            _requirement("ram_gb", 32, "ram-one", unit="GB"),
            _requirement("ram_gb", 32, "ram-two", unit="GB"),
        ],
    )

    assert [item.attribute_key for item in result.shared_requirements] == ["ram_gb"]
    assert "gpu_vram_gb" not in {item.attribute_key for item in result.shared_requirements}
    assert {issue.code for issue in result.issues} == {"requirement_claim_not_compiled"}
    assert {issue.claim_id for issue in result.issues} == {"invented-vram"}


def test_partially_grounded_hypothesis_survives_but_unsupported_claim_is_excluded():
    result = compile_workload_hypotheses(
        HypothesisSetProposal(
            hypotheses=[
                HypothesisProposal(
                    hypothesis_id="local",
                    label="Local execution",
                    requirement_claim_ids=["known", "unknown"],
                )
            ]
        ),
        compiled_requirements=[_requirement("ram_gb", 32, "known", unit="GB")],
    )

    assert result.hypotheses[0].grounded_claim_ids == ["known"]
    assert result.hypotheses[0].excluded_claim_ids == ["unknown"]
    assert result.shared_requirements[0].attribute_key == "ram_gb"


def test_completely_ungrounded_hypothesis_is_rejected_not_presented_as_interpretation():
    with pytest.raises(ValueError, match="hypothesis_has_no_grounded_requirements"):
        compile_workload_hypotheses(
            HypothesisSetProposal(
                hypotheses=[
                    HypothesisProposal(
                        hypothesis_id="invented",
                        label="Invented interpretation",
                        requirement_claim_ids=["missing"],
                    )
                ]
            ),
            compiled_requirements=[],
        )


def test_different_values_on_same_attribute_form_one_divergent_axis():
    result = compile_workload_hypotheses(
        HypothesisSetProposal(
            hypotheses=[
                HypothesisProposal(
                    hypothesis_id="small",
                    label="Small workload",
                    requirement_claim_ids=["small-ram"],
                ),
                HypothesisProposal(
                    hypothesis_id="large",
                    label="Large workload",
                    requirement_claim_ids=["large-ram"],
                ),
            ]
        ),
        compiled_requirements=[
            _requirement("ram_gb", 32, "small-ram", unit="GB"),
            _requirement("ram_gb", 64, "large-ram", unit="GB"),
        ],
    )

    assert result.shared_requirements == []
    assert len(result.divergent_axes) == 1
    assert result.divergent_axes[0].attribute_key == "ram_gb"
    assert result.divergent_axes[0].reason == "requirement_values_differ"


def test_selects_exactly_one_highest_impact_question_for_a_divergent_axis():
    result = compile_workload_hypotheses(
        HypothesisSetProposal(
            hypotheses=[
                HypothesisProposal(
                    hypothesis_id="local",
                    label="Local execution",
                    requirement_claim_ids=["local-gpu"],
                ),
                HypothesisProposal(
                    hypothesis_id="remote",
                    label="Remote client",
                    requirement_claim_ids=["remote-gpu"],
                ),
            ],
            question_candidates=[
                QuestionCandidate(
                    question_id="budget",
                    question="What is your budget?",
                    resolves_axes=["budget_cents"],
                    expected_candidate_reduction=0.80,
                    information_gain=0.90,
                ),
                QuestionCandidate(
                    question_id="execution-location",
                    question="Will the workload run locally, remotely, or in a hybrid setup?",
                    resolves_axes=["gpu_vram_gb"],
                    expected_candidate_reduction=0.60,
                    information_gain=0.85,
                ),
                QuestionCandidate(
                    question_id="weak-gpu-question",
                    question="Do you think you need a dedicated GPU?",
                    resolves_axes=["gpu_vram_gb"],
                    expected_candidate_reduction=0.20,
                    information_gain=0.30,
                ),
            ],
        ),
        compiled_requirements=[
            _requirement("gpu_vram_gb", 16, "local-gpu", unit="GB"),
            _requirement("gpu_vram_gb", 0, "remote-gpu", unit="GB"),
        ],
    )

    assert result.next_question is not None
    assert result.next_question.question_id == "execution-location"
    assert len(result.eligible_questions) == 2
    assert {item.question_id for item in result.eligible_questions} == {
        "execution-location",
        "weak-gpu-question",
    }


def test_no_divergent_axis_means_no_material_question():
    result = compile_workload_hypotheses(
        HypothesisSetProposal(
            hypotheses=[
                HypothesisProposal(
                    hypothesis_id="known",
                    label="Known workload",
                    requirement_claim_ids=["ram"],
                )
            ],
            question_candidates=[
                QuestionCandidate(
                    question_id="budget",
                    question="What is your budget?",
                    resolves_axes=["budget_cents"],
                    expected_candidate_reduction=0.9,
                    information_gain=0.9,
                )
            ],
        ),
        compiled_requirements=[_requirement("ram_gb", 32, "ram", unit="GB")],
    )

    assert result.divergent_axes == []
    assert result.next_question is None
    assert result.eligible_questions == []
