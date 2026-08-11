"""Compile grounded workload interpretations into shared and divergent requirements.

The language model may propose a small set of interpretations and useful questions, but it
does not grant requirement authority.  This reducer admits only claim identifiers already
present in ``CompiledRequirement`` rows, computes their exact intersection, and selects one
question that addresses a material divergent axis.  It contains no workload, product, or
vertical vocabulary.
"""

from __future__ import annotations

import json
from collections import defaultdict
from typing import Any, Iterable, Literal, Sequence

from pydantic import BaseModel, ConfigDict, Field

from src.app.services.recommendation_core.research_contracts import CompiledRequirement


class HypothesisProposal(BaseModel):
    """A model-proposed interpretation whose requirements must resolve to compiled claims."""

    model_config = ConfigDict(extra="forbid")

    hypothesis_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,59}$")
    label: str = Field(min_length=2, max_length=160)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    requirement_claim_ids: list[str] = Field(min_length=1, max_length=32)
    material_unknown_ids: list[str] = Field(default_factory=list, max_length=8)
    authority: Literal["proposed"] = "proposed"


class QuestionCandidate(BaseModel):
    """A bounded question proposal with model/evaluator supplied impact estimates."""

    model_config = ConfigDict(extra="forbid")

    question_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,59}$")
    question: str = Field(min_length=3, max_length=240)
    resolves_axes: list[str] = Field(min_length=1, max_length=8)
    expected_candidate_reduction: float = Field(default=0.0, ge=0.0, le=1.0)
    information_gain: float = Field(default=0.0, ge=0.0, le=1.0)
    authority: Literal["proposed"] = "proposed"


class HypothesisSetProposal(BaseModel):
    """The intentionally small proposal consumed by the deterministic compiler."""

    model_config = ConfigDict(extra="forbid")

    hypotheses: list[HypothesisProposal] = Field(min_length=1, max_length=3)
    question_candidates: list[QuestionCandidate] = Field(default_factory=list, max_length=8)


class RequirementProjection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    attribute_key: str
    operator: Literal[">=", "<=", "=", "in", "contains"]
    value: str | float | int | bool
    unit: str | None = None
    requirement_class: Literal["minimum", "recommended", "target", "optimal"]
    source_claim_ids: list[str]
    authority: Literal["accepted_evidence"] = "accepted_evidence"


class GroundedHypothesis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hypothesis_id: str
    label: str
    confidence: float
    grounded_claim_ids: list[str]
    excluded_claim_ids: list[str]
    requirements: list[RequirementProjection]
    material_unknown_ids: list[str]
    authority: Literal["grounded_proposal"] = "grounded_proposal"


class DivergentAxis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    attribute_key: str
    reason: Literal["requirement_values_differ", "requirement_absent_in_some_hypotheses"]
    variants: dict[str, list[RequirementProjection]]


class CompilationIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: Literal["requirement_claim_not_compiled"]
    hypothesis_id: str
    claim_id: str


class WorkloadHypothesisCompilation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["workload-hypothesis-compilation-v1"] = (
        "workload-hypothesis-compilation-v1"
    )
    hypotheses: list[GroundedHypothesis] = Field(min_length=1, max_length=3)
    shared_requirements: list[RequirementProjection]
    divergent_axes: list[DivergentAxis]
    eligible_questions: list[QuestionCandidate]
    next_question: QuestionCandidate | None = None
    issues: list[CompilationIssue]


def _normalized_value(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _signature(requirement: CompiledRequirement) -> tuple[str, str, str, str, str]:
    return (
        requirement.attribute_key.strip().lower(),
        requirement.operator,
        _normalized_value(requirement.value),
        str(requirement.unit or "").strip().lower(),
        requirement.requirement_class,
    )


def _projection(
    requirement: CompiledRequirement,
    *,
    source_claim_ids: Iterable[str] | None = None,
) -> RequirementProjection:
    return RequirementProjection(
        attribute_key=requirement.attribute_key,
        operator=requirement.operator,
        value=requirement.value,
        unit=requirement.unit,
        requirement_class=requirement.requirement_class,
        source_claim_ids=sorted(set(source_claim_ids or requirement.source_claim_ids)),
    )


def compile_workload_hypotheses(
    proposal: HypothesisSetProposal,
    *,
    compiled_requirements: Sequence[CompiledRequirement],
) -> WorkloadHypothesisCompilation:
    """Ground a bounded proposal and derive the shared floor and divergent axes.

    A hypothesis with at least one accepted claim remains useful while its unsupported claim
    references are exposed as issues.  A wholly ungrounded hypothesis is rejected because
    presenting it as an evidence-led interpretation would be misleading.
    """
    claim_index: dict[str, CompiledRequirement] = {}
    for requirement in compiled_requirements:
        for claim_id in requirement.source_claim_ids:
            existing = claim_index.get(claim_id)
            if existing is not None and _signature(existing) != _signature(requirement):
                raise ValueError(f"compiled_claim_id_is_ambiguous:{claim_id}")
            claim_index[claim_id] = requirement

    grounded: list[GroundedHypothesis] = []
    issues: list[CompilationIssue] = []
    requirements_by_hypothesis: dict[str, dict[tuple[str, str, str, str, str], CompiledRequirement]] = {}
    claim_ids_by_hypothesis_signature: dict[
        tuple[str, tuple[str, str, str, str, str]], set[str]
    ] = defaultdict(set)

    for hypothesis in proposal.hypotheses:
        resolved_ids: list[str] = []
        excluded_ids: list[str] = []
        unique_requirements: dict[
            tuple[str, str, str, str, str], CompiledRequirement
        ] = {}
        for claim_id in dict.fromkeys(hypothesis.requirement_claim_ids):
            matched_requirement = claim_index.get(claim_id)
            if matched_requirement is None:
                excluded_ids.append(claim_id)
                issues.append(
                    CompilationIssue(
                        code="requirement_claim_not_compiled",
                        hypothesis_id=hypothesis.hypothesis_id,
                        claim_id=claim_id,
                    )
                )
                continue
            resolved_ids.append(claim_id)
            signature = _signature(matched_requirement)
            unique_requirements[signature] = matched_requirement
            claim_ids_by_hypothesis_signature[(hypothesis.hypothesis_id, signature)].add(claim_id)

        if not unique_requirements:
            raise ValueError(
                f"hypothesis_has_no_grounded_requirements:{hypothesis.hypothesis_id}"
            )
        requirements_by_hypothesis[hypothesis.hypothesis_id] = unique_requirements
        grounded.append(
            GroundedHypothesis(
                hypothesis_id=hypothesis.hypothesis_id,
                label=hypothesis.label,
                confidence=hypothesis.confidence,
                grounded_claim_ids=resolved_ids,
                excluded_claim_ids=excluded_ids,
                requirements=[
                    _projection(
                        requirement,
                        source_claim_ids=claim_ids_by_hypothesis_signature[
                            (hypothesis.hypothesis_id, signature)
                        ],
                    )
                    for signature, requirement in sorted(unique_requirements.items())
                ],
                material_unknown_ids=hypothesis.material_unknown_ids,
            )
        )

    signature_sets = [set(items) for items in requirements_by_hypothesis.values()]
    shared_signatures = set.intersection(*signature_sets)
    shared: list[RequirementProjection] = []
    for signature in sorted(shared_signatures):
        representative = next(
            requirements[signature] for requirements in requirements_by_hypothesis.values()
        )
        source_ids = {
            claim_id
            for hypothesis_id in requirements_by_hypothesis
            for claim_id in claim_ids_by_hypothesis_signature[(hypothesis_id, signature)]
        }
        shared.append(_projection(representative, source_claim_ids=source_ids))

    divergent_signatures = {
        signature
        for signatures in signature_sets
        for signature in signatures
        if signature not in shared_signatures
    }
    divergent_by_attribute: dict[str, set[tuple[str, str, str, str, str]]] = defaultdict(set)
    for signature in divergent_signatures:
        divergent_by_attribute[signature[0]].add(signature)

    divergent_axes: list[DivergentAxis] = []
    for attribute_key in sorted(divergent_by_attribute):
        variants: dict[str, list[RequirementProjection]] = {}
        missing = False
        for hypothesis_id, requirements in requirements_by_hypothesis.items():
            rows = [
                (signature, requirement)
                for signature, requirement in requirements.items()
                if signature in divergent_by_attribute[attribute_key]
            ]
            if not rows:
                missing = True
            variants[hypothesis_id] = [
                _projection(
                    requirement,
                    source_claim_ids=claim_ids_by_hypothesis_signature[
                        (hypothesis_id, signature)
                    ],
                )
                for signature, requirement in sorted(rows)
            ]
        divergent_axes.append(
            DivergentAxis(
                attribute_key=attribute_key,
                reason=(
                    "requirement_absent_in_some_hypotheses"
                    if missing
                    else "requirement_values_differ"
                ),
                variants=variants,
            )
        )

    divergent_keys = {axis.attribute_key for axis in divergent_axes}
    eligible_questions = [
        question
        for question in proposal.question_candidates
        if divergent_keys.intersection(question.resolves_axes)
    ]
    eligible_questions.sort(
        key=lambda item: (
            -item.information_gain,
            -item.expected_candidate_reduction,
            -len(divergent_keys.intersection(item.resolves_axes)),
            item.question_id,
        )
    )

    return WorkloadHypothesisCompilation(
        hypotheses=grounded,
        shared_requirements=shared,
        divergent_axes=divergent_axes,
        eligible_questions=eligible_questions,
        next_question=eligible_questions[0] if eligible_questions else None,
        issues=issues,
    )


__all__ = [
    "CompilationIssue",
    "DivergentAxis",
    "GroundedHypothesis",
    "HypothesisProposal",
    "HypothesisSetProposal",
    "QuestionCandidate",
    "RequirementProjection",
    "WorkloadHypothesisCompilation",
    "compile_workload_hypotheses",
]
