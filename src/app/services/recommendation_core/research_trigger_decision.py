"""Deterministic coverage gate for optional external research.

The gate is deliberately product-vertical agnostic.  It consumes coverage and
decision-impact signals produced elsewhere; it does not classify a workload, select a
provider, or execute research.  In particular, eligibility and authorization are
separate so a corpus miss can never spend external credits by itself.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


ProfileCoverage = Literal["covered", "partial", "miss", "unknown"]
EvidenceCoverage = Literal["sufficient", "partial", "miss", "stale", "unknown"]
AuthorizationState = Literal["not_requested", "granted", "denied"]
ResearchRoute = Literal[
    "local_evidence",
    "provisional_catalog",
    "request_authorization",
    "external_research",
    "request_buyer_evidence",
]


class ResearchTriggerDecision(BaseModel):
    """Auditable routing result; never an authority to call a provider on its own."""

    model_config = ConfigDict(extra="forbid")

    version: Literal["research-trigger-v1"] = "research-trigger-v1"
    interpretation_confidence: float = Field(ge=0.0, le=1.0)
    workload_profile_coverage: ProfileCoverage
    corpus_coverage: EvidenceCoverage
    cache_coverage: EvidenceCoverage
    material_unknowns: list[str] = Field(default_factory=list, max_length=12)
    expected_decision_impact: float = Field(ge=0.0, le=1.0)
    external_research_eligible: bool
    authorization_required: bool
    authorization_state: AuthorizationState
    should_execute_external_research: bool
    route: ResearchRoute
    reason_codes: list[str]
    authoritative: Literal[False] = False


def decide_research_trigger(
    *,
    interpretation_confidence: float,
    workload_profile_coverage: ProfileCoverage,
    corpus_coverage: EvidenceCoverage,
    cache_coverage: EvidenceCoverage,
    material_unknowns: list[str] | tuple[str, ...] = (),
    expected_decision_impact: float,
    authorization_state: AuthorizationState = "not_requested",
    external_research_allowed: bool = True,
) -> ResearchTriggerDecision:
    """Choose the cheapest safe evidence route from already-computed signals.

    ``expected_decision_impact`` describes how much resolving the evidence gap is
    expected to change qualification or ranking.  A gap with little decision impact is
    not a reason to search.  Fresh sufficient corpus or cache coverage always wins over
    external research, even for an unfamiliar workload label.
    """

    confidence = _unit(interpretation_confidence)
    impact = _unit(expected_decision_impact)
    unknowns = list(dict.fromkeys(
        str(item).strip() for item in material_unknowns if str(item).strip()
    ))[:12]
    local_evidence_sufficient = (
        corpus_coverage == "sufficient" or cache_coverage == "sufficient"
    )
    profile_gap = workload_profile_coverage in {"partial", "miss", "unknown"}
    interpretation_gap = confidence < 0.60
    evidence_gap = not local_evidence_sufficient
    material_impact = impact >= 0.50
    material_gap = bool(unknowns) or profile_gap or interpretation_gap

    eligible = bool(evidence_gap and material_impact and material_gap)
    authorization_required = eligible
    should_execute = bool(
        eligible and external_research_allowed and authorization_state == "granted"
    )

    reasons: list[str] = []
    if local_evidence_sufficient:
        reasons.append(
            "fresh_corpus_sufficient"
            if corpus_coverage == "sufficient"
            else "fresh_cache_sufficient"
        )
    if profile_gap:
        reasons.append("workload_profile_gap")
    if interpretation_gap:
        reasons.append("low_interpretation_confidence")
    if corpus_coverage in {"miss", "stale", "unknown"}:
        reasons.append(f"corpus_{corpus_coverage}")
    if cache_coverage in {"miss", "stale", "unknown"}:
        reasons.append(f"cache_{cache_coverage}")
    if unknowns:
        reasons.append("material_unknowns")
    if not material_impact:
        reasons.append("low_decision_impact")
    if eligible and not external_research_allowed:
        reasons.append("external_research_not_allowed")
    elif eligible and authorization_state == "denied":
        reasons.append("buyer_declined_external_research")
    elif eligible and authorization_state == "not_requested":
        reasons.append("external_authorization_required")
    elif should_execute:
        reasons.append("external_research_authorized")

    if local_evidence_sufficient:
        route: ResearchRoute = "local_evidence"
    elif eligible and (not external_research_allowed or authorization_state == "denied"):
        route = "request_buyer_evidence"
    elif should_execute:
        route = "external_research"
    elif eligible:
        route = "request_authorization"
    else:
        route = "provisional_catalog"

    return ResearchTriggerDecision(
        interpretation_confidence=confidence,
        workload_profile_coverage=workload_profile_coverage,
        corpus_coverage=corpus_coverage,
        cache_coverage=cache_coverage,
        material_unknowns=unknowns,
        expected_decision_impact=impact,
        external_research_eligible=eligible,
        authorization_required=authorization_required,
        authorization_state=authorization_state,
        should_execute_external_research=should_execute,
        route=route,
        reason_codes=reasons,
    )


def _unit(value: float) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0
