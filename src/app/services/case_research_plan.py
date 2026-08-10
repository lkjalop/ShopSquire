"""Case-bound, publisher-governed research planning.

The planner contains no workload enum or provider name.  It projects candidate
research scopes from the governed source manifest and binds them to the buyer's
retained purpose.  Candidate scopes may include sources awaiting policy review;
execution performs a second approval check and can never inherit authority from
this proposal.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field

from src.app.services.official_source_governance import load_official_source_manifest


_TOKEN = re.compile(r"[a-z0-9]+")
_ACRONYM = re.compile(r"\b[A-Z][A-Z0-9+.-]{1,7}\b")
_STOP = {
    "a", "an", "and", "are", "as", "at", "be", "buyer", "current", "do",
    "for", "from", "generic", "hardware", "i", "in", "is", "it", "large",
    "local", "named", "of", "official", "only", "or", "requirements", "scope",
    "software", "system", "the", "to", "use", "with", "workload",
}
_GENERIC_ACTIVATION_PHRASES = {
    "requirement", "system requirement", "hardware requirement",
    "software requirement", "minimum requirement", "recommended requirement",
}


class CaseResearchHypothesis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hypothesis_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    label: str = Field(min_length=2, max_length=200)
    source_ids: list[str] = Field(min_length=1, max_length=8)
    authority: Literal["proposed"] = "proposed"


class CaseAmbiguityObject(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ambiguity_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    ambiguity_type: str = Field(min_length=2, max_length=100)
    subject_span: str = Field(min_length=1, max_length=240)
    description: str = Field(min_length=2, max_length=300)
    hypothesis_ids: list[str] = Field(min_length=1, max_length=3)
    resolution_owners: list[
        Literal["catalog", "research", "buyer", "computation", "supplier", "tenant_policy", "human"]
    ] = Field(min_length=1, max_length=4)
    divergent_axes: list[str] = Field(default_factory=list, max_length=8)


class CaseResearchObligation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    obligation_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    obligation_type: str = Field(min_length=2, max_length=100)
    description: str = Field(min_length=2, max_length=300)
    resolution_owner: Literal[
        "catalog", "research", "buyer", "computation", "supplier", "tenant_policy", "human"
    ]
    status: Literal["unresolved", "planned", "resolved", "blocked"] = "unresolved"


class CaseResearchPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["case-research-plan-v1"] = "case-research-plan-v1"
    plan_id: str = Field(pattern=r"^crp-[a-f0-9]{20}$")
    retained_purpose: str = Field(min_length=3, max_length=500)
    ambiguities: list[CaseAmbiguityObject] = Field(min_length=1, max_length=8)
    hypotheses: list[CaseResearchHypothesis] = Field(min_length=1, max_length=3)
    source_candidate_ids: list[str] = Field(min_length=1, max_length=16)
    obligations: list[CaseResearchObligation] = Field(min_length=1, max_length=16)
    next_question: str = Field(min_length=3, max_length=300)
    external_calls: Literal[0] = 0
    authority: Literal["proposal_only"] = "proposal_only"


def _tokens(value: str) -> set[str]:
    return {token for token in _TOKEN.findall(str(value or "").lower()) if token not in _STOP}


def _source_terms(source: Mapping[str, Any]) -> set[str]:
    applicability = source.get("applicability") or {}
    values: list[str] = [
        str(source.get("publisher") or ""),
        str(applicability.get("scope") or ""),
        *[str(item).replace("_", " ") for item in applicability.get("workloads") or []],
        *[str(item) for item in source.get("artefact_patterns") or []],
    ]
    return _tokens(" ".join(values))


def _normalized_phrase(value: str) -> str:
    tokens = _TOKEN.findall(str(value or "").replace("_", " ").lower())
    return " ".join(token[:-1] if len(token) > 4 and token.endswith("s") else token for token in tokens)


def _source_phrases(source: Mapping[str, Any]) -> set[str]:
    applicability = source.get("applicability") or {}
    return {
        phrase
        for phrase in (
            *[_normalized_phrase(item) for item in applicability.get("workloads") or []],
            *[_normalized_phrase(item) for item in source.get("artefact_patterns") or []],
        )
        if phrase and phrase not in _GENERIC_ACTIVATION_PHRASES
    }


def candidate_sources_for_purpose(
    retained_purpose: str,
    *,
    manifest: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], ...]:
    """Return bounded source-scope candidates without granting execution authority."""

    purpose_tokens = _tokens(retained_purpose)
    if not purpose_tokens:
        return ()
    normalized_purpose = f" {_normalized_phrase(retained_purpose)} "
    buyer_acronyms = {item.lower().strip("+.-") for item in _ACRONYM.findall(retained_purpose)}
    source_manifest = dict(manifest or load_official_source_manifest())
    ranked: list[tuple[int, str, dict[str, Any]]] = []
    for raw in source_manifest.get("sources") or []:
        source = dict(raw)
        activation = source.get("activation_policy") or {}
        required_any_terms = {
            _normalized_phrase(value)
            for value in activation.get("required_any_terms") or []
            if _normalized_phrase(value)
        }
        if required_any_terms and not any(
            f" {term} " in normalized_purpose for term in required_any_terms
        ):
            continue
        phrases = _source_phrases(source)
        exact_phrases = {
            phrase for phrase in phrases
            if f" {phrase} " in normalized_purpose
        }
        acronym_hits = buyer_acronyms & _source_terms(source)
        if not exact_phrases and not acronym_hits:
            continue
        score = sum(len(phrase.split()) + 2 for phrase in exact_phrases) + 4 * len(acronym_hits)
        ranked.append((-score, str(source.get("source_id") or ""), source))
    ranked.sort(key=lambda item: (item[0], item[1]))
    return tuple(item[2] for item in ranked[:8])


def _hypothesis_label(source: Mapping[str, Any]) -> str:
    scope = str((source.get("applicability") or {}).get("scope") or "").strip()
    return scope[:200] or str(source.get("publisher") or "Official workload scope")[:200]


def build_case_research_plan(
    retained_purpose: str,
    *,
    manifest: Mapping[str, Any] | None = None,
) -> CaseResearchPlan | None:
    sources = candidate_sources_for_purpose(retained_purpose, manifest=manifest)
    if not sources:
        return None
    hypotheses: list[CaseResearchHypothesis] = []
    for index, source in enumerate(sources[:3], 1):
        hypotheses.append(CaseResearchHypothesis(
            hypothesis_id=f"scope_{index}_{str(source['source_id'])[:42].replace('-', '_')}",
            label=_hypothesis_label(source), source_ids=[str(source["source_id"])],
        ))
    pending = any(source.get("review_status") != "approved" for source in sources)
    source_ids = [str(source["source_id"]) for source in sources]
    material = "|".join([retained_purpose.strip(), *source_ids, *[row.hypothesis_id for row in hypotheses]])
    plan_id = "crp-" + hashlib.sha256(material.encode()).hexdigest()[:20]
    obligations = [
        CaseResearchObligation(
            obligation_id="workload_meaning", obligation_type="workload_interpretation",
            description="Resolve which proposed workload scope the buyer intends.",
            resolution_owner="buyer",
        ),
        CaseResearchObligation(
            obligation_id="official_requirements", obligation_type="current_requirements",
            description="Retrieve and normalize applicable official publisher requirements.",
            resolution_owner="research", status="planned",
        ),
        CaseResearchObligation(
            obligation_id="exact_product_identity", obligation_type="product_configuration",
            description="Corroborate exact catalog configurations against accepted claims.",
            resolution_owner="catalog", status="planned",
        ),
    ]
    if pending:
        obligations.append(CaseResearchObligation(
            obligation_id="publisher_approval", obligation_type="publisher_policy",
            description="Approve applicable publisher policies before live execution.",
            resolution_owner="tenant_policy",
        ))
    ambiguity = CaseAmbiguityObject(
        ambiguity_id="workload_scope",
        ambiguity_type="workload_scope",
        subject_span=retained_purpose[:240],
        description="Several governed publisher scopes may materially change product fit.",
        hypothesis_ids=[row.hypothesis_id for row in hypotheses],
        resolution_owners=["buyer", "research", "tenant_policy" if pending else "catalog"],
        divergent_axes=["named_software", "local_execution_scope", "dataset_or_project_scale"],
    )
    return CaseResearchPlan(
        plan_id=plan_id, retained_purpose=retained_purpose[:500],
        ambiguities=[ambiguity], hypotheses=hypotheses,
        source_candidate_ids=source_ids, obligations=obligations,
        next_question=(
            "Which named software and version will you use, and which simulation, rendering, "
            "or processing stages must run locally?"
        ),
    )


def approved_sources_for_plan(
    plan: CaseResearchPlan,
    *,
    manifest: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], ...]:
    source_manifest = dict(manifest or load_official_source_manifest())
    wanted = set(plan.source_candidate_ids)
    return tuple(
        dict(source) for source in source_manifest.get("sources") or []
        if source.get("source_id") in wanted and source.get("review_status") == "approved"
    )


def plan_hypothesis_labels(plan: CaseResearchPlan) -> dict[str, str]:
    return {row.hypothesis_id: row.label for row in plan.hypotheses}


__all__ = [
    "CaseAmbiguityObject", "CaseResearchHypothesis", "CaseResearchObligation",
    "CaseResearchPlan", "approved_sources_for_plan", "build_case_research_plan",
    "candidate_sources_for_purpose", "plan_hypothesis_labels",
]
