"""Agnostic semantic resolution between language interpretation and catalog authority.

The model may propose an outcome, unfamiliar concepts and useful questions.  This module
does not know games, software, materials, medical devices or product verticals.  It only
validates that concepts are anchored in the buyer's text, normalizes evidence provenance,
and deterministically decides whether catalog selection may proceed.
"""

from __future__ import annotations

import os
import re
from dataclasses import asdict, dataclass
from typing import Any, Literal, Sequence

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from src.app.services.recommendation_core.research_contracts import ClaimType


ConceptStatus = Literal["resolved", "unresolved", "ambiguous"]
SemanticAction = Literal[
    "answer",
    "search_catalog",
    "research",
    "clarify",
    "research_then_clarify",
    "align_off_catalog",
]
ResidualRoute = Literal["ASK", "SEARCH", "CONNECTOR", "AUTHORIZE"]


class ConceptProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=2, max_length=120)
    # query_span is the buyer-authored anchor. normalized_label is advisory model
    # normalization only; neither field grants evidence or catalog authority.
    query_span: str | None = Field(default=None, min_length=2, max_length=120)
    normalized_label: str | None = Field(default=None, min_length=2, max_length=120)
    status: ConceptStatus = "unresolved"
    material: bool = True
    interpretations: list[str] = Field(default_factory=list, max_length=5)


class EvidenceQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_id: str = Field(min_length=1, max_length=60)
    question: str = Field(min_length=3, max_length=240)
    purpose: Literal[
        "resolve_concept",
        "resolve_compatibility",
        "resolve_performance_target",
        "resolve_product_identity",
        "resolve_safety_or_policy",
    ] = "resolve_concept"
    resolves_unknown_ids: list[str] = Field(default_factory=list, max_length=4)
    decision_impacts: list[
        Literal["architecture", "capability", "affordable_quantity", "product_set"]
    ] = Field(default_factory=list, max_length=4)
    material: bool = True


class ProductCategoryCandidate(BaseModel):
    """A model-proposed category label with no sellability or retrieval authority."""

    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=2, max_length=120)
    taxonomy_handle: str | None = Field(default=None, min_length=2, max_length=160)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    authority: Literal["proposed"] = "proposed"


class WorkloadHypothesis(BaseModel):
    """One bounded interpretation to investigate, never an accepted workload fact."""

    model_config = ConfigDict(extra="forbid")

    hypothesis_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,59}$")
    label: str = Field(min_length=2, max_length=160)
    evidence_needed: list[str] = Field(default_factory=list, max_length=6)
    required_claim_types: list[ClaimType] = Field(default_factory=list, max_length=6)
    discriminating_unknown_ids: list[str] = Field(default_factory=list, max_length=6)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    authority: Literal["proposed"] = "proposed"


class MaterialUnknown(BaseModel):
    """A material gap and the bounded authority capable of resolving it."""

    model_config = ConfigDict(extra="forbid")

    unknown_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,59}$")
    description: str = Field(min_length=2, max_length=200)
    resolution_source: Literal["research", "buyer", "either"]
    material: bool = True


class SemanticProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    desired_outcome: str = Field(min_length=2, max_length=240)
    product_category_candidates: list[ProductCategoryCandidate] = Field(
        default_factory=list, max_length=5
    )
    concepts: list[ConceptProposal] = Field(default_factory=list, max_length=4)
    workload_hypotheses: list[WorkloadHypothesis] = Field(default_factory=list, max_length=5)
    material_unknowns: list[MaterialUnknown] = Field(default_factory=list, max_length=8)
    evidence_questions: list[EvidenceQuestion] = Field(default_factory=list, max_length=5)
    proposed_action: SemanticAction = "search_catalog"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    proposal_origin: Literal[
        "model", "deterministic_fallback", "coverage_abstention", "persisted"
    ] = "model"


@dataclass(frozen=True)
class SemanticValidation:
    outcome: Literal["valid", "rejected"]
    reasons: tuple[str, ...]
    proposal: SemanticProposal | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "outcome": self.outcome,
            "reasons": list(self.reasons),
            "proposal": self.proposal.model_dump() if self.proposal else None,
        }


@dataclass(frozen=True)
class ConceptEvidence:
    concept: str
    status: Literal["resolved", "insufficient", "contradictory", "unavailable"]
    claim: str
    claim_status: Literal["verified", "unverified", "contradictory"]
    claim_type: str | None = None
    source_id: str | None = None
    source_record_id: str | None = None
    source_revision: str | None = None
    observed_at: str | None = None
    citation_id: str | None = None
    source_policy_status: str = "unverified"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SemanticDecision:
    outcome: Literal["proceed_catalog", "clarify", "research", "rejected"]
    catalog_authority: Literal["permitted", "blocked"]
    reasons: tuple[str, ...]
    questions: tuple[dict[str, Any], ...] = ()
    concepts: tuple[dict[str, Any], ...] = ()
    evidence: tuple[dict[str, Any], ...] = ()
    state_prevented: tuple[str, ...] = ()
    next_permitted_action: str = ""
    desired_outcome: str = ""
    product_category_candidates: tuple[dict[str, Any], ...] = ()
    workload_hypotheses: tuple[dict[str, Any], ...] = ()
    material_unknowns: tuple[dict[str, Any], ...] = ()
    interpretation_confidence: float = 0.0
    residual_route: ResidualRoute = "ASK"
    residual_reasons: tuple[str, ...] = ()
    # This is deliberately false even when residual_route=AUTHORIZE. The semantic
    # reducer can identify the next authority boundary; only policy-as-code can grant it.
    authorization_granted: bool = False

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CatalogAlignment:
    status: Literal[
        "blocked",
        "exact_catalog_match",
        "qualified_catalog_match",
        "no_exact_catalog_match",
        "unsupported",
    ]
    exact: tuple[str, ...] = ()
    qualified: tuple[str, ...] = ()
    alternatives: tuple[str, ...] = ()
    unverified: tuple[str, ...] = ()
    permitted_actions: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _tokens(value: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", str(value or "").lower()))


_GENERIC_MATERIAL_RELATIONS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "material_identity",
        re.compile(
            r"\bmade\s+(?:of|from|with)\s+(?P<concept>[^,.;?]{2,100}?)(?=\s+for\b|[,.;?]|$)",
            re.IGNORECASE,
        ),
    ),
    (
        "compatibility_target",
        re.compile(
            r"\bcompatible\s+with\s+(?P<concept>[^,.;?]{2,100})(?=[,.;?]|$)",
            re.IGNORECASE,
        ),
    ),
    (
        "standard_or_certification",
        re.compile(
            r"\b(?:certified|compliant)\s+(?:for|with|to)\s+"
            r"(?P<concept>[^,.;?]{2,100})(?=[,.;?]|$)",
            re.IGNORECASE,
        ),
    ),
    (
        "capability_outcome",
        re.compile(
            r"\b(?:capable\s+(?:of|for)|suitable\s+for|powerful\s+enough\s+for)\s+"
            r"(?P<concept>[^,.;?]{2,120})(?=[,.;?]|$)",
            re.IGNORECASE,
        ),
    ),
    (
        "capability_outcome",
        re.compile(
            r"\bfor\s+(?P<concept>(?:simulat|render|model|process|analys|analyz|train|run)"
            r"[a-z]*\b[^,.;?]{0,100})(?=[,.;?]|$)",
            re.IGNORECASE,
        ),
    ),
)


def fallback_semantic_proposal(
    *,
    query: str,
    exact_product_sku: str | None = None,
    requirements: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a conservative proposal when the model omitted a material relation.

    This is grammar over *relations*, not a product or workload knowledge table.  It cannot
    decide that a SKU is suitable.  It only recognizes that a buyer attached an unresolved
    capability, material, compatibility or certification condition and asks for evidence that
    could change fit.  A literal SKU or already-explicit numeric requirements do not suppress
    the gate: the named product may still fail the requested outcome.
    """
    text = str(query or "").strip()
    if not text:
        return {}
    relation = ""
    concept = ""
    for candidate_relation, pattern in _GENERIC_MATERIAL_RELATIONS:
        match = pattern.search(text)
        if match:
            relation = candidate_relation
            concept = str(match.group("concept") or "").strip()
            break
    if not relation or len(_tokens(concept)) < 1:
        return {}

    # Keep the literal query span as the concept anchor.  The validator below will reject any
    # accidental drift, so this fallback can never manufacture a domain fact.
    questions: list[dict[str, Any]]
    if relation == "capability_outcome":
        questions = [
            {
                "question_id": "software_or_standard",
                "question": "Which exact software, standard, or workflow and version must be supported?",
                "purpose": "resolve_compatibility",
                "resolves_unknown_ids": ["material-concept"],
                "decision_impacts": ["capability", "product_set"],
                "material": True,
            },
            {
                "question_id": "execution_location",
                "question": "Will the work run locally on each device, remotely, or in a hybrid setup?",
                "purpose": "resolve_compatibility",
                "resolves_unknown_ids": ["execution-location"],
                "decision_impacts": ["architecture", "capability", "product_set"],
                "material": True,
            },
            {
                "question_id": "performance_target",
                "question": (
                    "What workload or model scale and time-to-result target should define acceptable "
                    "performance?"
                ),
                "purpose": "resolve_performance_target",
                "resolves_unknown_ids": ["performance-target"],
                "decision_impacts": ["capability", "affordable_quantity", "product_set"],
                "material": True,
            },
        ]
    elif relation == "material_identity":
        questions = [{
            "question_id": "material_identity",
            "question": (
                "Which verified species, grade, finish, certification, or supplier material "
                "standard must the product satisfy?"
            ),
            "purpose": "resolve_concept",
            "material": True,
        }]
    else:
        questions = [{
            "question_id": relation,
            "question": (
                "Which exact version, interface, jurisdiction, test standard, or certification "
                "must be verified?"
            ),
            "purpose": "resolve_compatibility",
            "material": True,
        }]

    return {
        "validation": "valid",
        "desired_outcome": text[:240],
        "product_category_candidates": [],
        "concepts": [{
            "text": concept[:120],
            "query_span": concept[:120],
            "status": "unresolved",
            "material": True,
            "interpretations": [],
        }],
        # A deterministic relation recognizer may detect uncertainty, but it must not
        # invent competing domain interpretations. Those belong to the model proposal.
        "workload_hypotheses": [],
        "material_unknowns": [{
            "unknown_id": "material-concept",
            "description": f"Authoritative meaning and requirements for {concept[:120]}",
            "resolution_source": "research",
            "material": True,
        }, {
            "unknown_id": "execution-location",
            "description": "Whether execution is local, remote, or hybrid",
            "resolution_source": "buyer",
            "material": True,
        }, {
            "unknown_id": "performance-target",
            "description": "Buyer-required scale and time-to-result target",
            "resolution_source": "buyer",
            "material": True,
        }],
        "evidence_questions": questions,
        "proposed_action": "research_then_clarify",
        # This is a conservative parser fallback, not model certainty and not
        # evidence authority.  Keep the confidence visibly below a model-backed
        # interpretation so traces and harnesses can distinguish the two.
        "confidence": 0.35,
        "proposal_origin": "deterministic_fallback",
    }


def validate_semantic_proposal(raw: Any, *, query: str) -> SemanticValidation:
    """Validate bounded model output without granting catalog or research authority."""
    try:
        proposal = SemanticProposal.model_validate(raw)
    except ValidationError:
        return SemanticValidation("rejected", ("proposal_schema_invalid",))

    query_tokens = _tokens(query)
    for concept in proposal.concepts:
        anchor_tokens = _tokens(concept.query_span or concept.text)
        if not anchor_tokens or not anchor_tokens <= query_tokens:
            return SemanticValidation("rejected", ("concept_not_anchored_in_query",))

    question_ids = [item.question_id for item in proposal.evidence_questions]
    if len(question_ids) != len(set(question_ids)):
        return SemanticValidation("rejected", ("duplicate_evidence_question",))
    hypothesis_ids = [item.hypothesis_id for item in proposal.workload_hypotheses]
    if len(hypothesis_ids) != len(set(hypothesis_ids)):
        return SemanticValidation("rejected", ("duplicate_workload_hypothesis",))
    unknown_ids = [item.unknown_id for item in proposal.material_unknowns]
    if len(unknown_ids) != len(set(unknown_ids)):
        return SemanticValidation("rejected", ("duplicate_material_unknown",))
    known_unknown_ids = set(unknown_ids)
    if any(
        set(item.discriminating_unknown_ids) - known_unknown_ids
        for item in proposal.workload_hypotheses
    ):
        return SemanticValidation("rejected", ("hypothesis_unknown_reference_invalid",))
    return SemanticValidation("valid", (), proposal)


def validate_semantic_source_policy(policy: Any, *, claim_type: str) -> tuple[bool, str]:
    """Fail-closed eligibility for evidence that may resolve a material concept.

    Registration and independent review are authority boundaries, not properties a
    search result can assert about itself.  Production registries should sign these
    records; this portable contract still rejects missing, draft, automated or
    claim-incompatible approvals.
    """
    if not isinstance(policy, dict):
        return False, "source_policy_missing"
    required = (
        "policy_version", "review_status", "reviewer_type", "reviewed_by",
        "licence", "trust_tier", "allowed_claim_types", "freshness_status",
    )
    missing = [key for key in required if not policy.get(key)]
    if missing:
        return False, "source_policy_incomplete"
    review_status = str(policy.get("review_status") or "").lower()
    if review_status == "simulation_contract":
        # A versioned synthetic contract can exercise the complete architecture in
        # local/test demonstrations, but it is not independent source approval.  It
        # requires two explicit controls and is structurally unavailable in staging
        # and production so it cannot silently promote real catalog or commerce
        # authority.
        app_env = str(os.getenv("APP_ENV", "local") or "local").strip().lower()
        enabled = str(os.getenv("SEMANTIC_SIMULATION_AUTHORITY_ENABLED", "") or "").lower() in {
            "1", "true", "yes", "on",
        }
        allowed_env = app_env in {"local", "dev", "development", "test", "testing"}
        valid_contract = (
            policy.get("simulation_only") is True
            and str(policy.get("reviewer_type") or "").lower() == "deterministic_fixture"
            and str(policy.get("trust_tier") or "").lower() == "simulation"
        )
        allowed_claims = {str(value).strip() for value in policy.get("allowed_claim_types") or []}
        if not (enabled and allowed_env and valid_contract and claim_type in allowed_claims):
            return False, "simulation_contract_not_permitted"
        if str(policy.get("freshness_status") or "").lower() != "fresh":
            return False, "source_policy_stale"
        return True, "simulation_contract"
    if review_status != "approved":
        return False, "source_policy_not_approved"
    if str(policy.get("reviewer_type")).lower() != "independent_human":
        return False, "source_policy_not_independently_reviewed"
    reviewer = str(policy.get("reviewed_by") or "").strip().lower()
    if reviewer in {"codex", "system", "agent", "automated", "self-review"}:
        return False, "source_policy_self_or_automated_review"
    if str(policy.get("freshness_status")).lower() != "fresh":
        return False, "source_policy_stale"
    allowed = {str(value).strip() for value in policy.get("allowed_claim_types") or []}
    if str(claim_type or "").strip() not in allowed:
        return False, "claim_type_not_authorized"
    return True, "approved"


def normalize_concept_evidence(items: Sequence[dict[str, Any]]) -> tuple[ConceptEvidence, ...]:
    """Normalize provider output; a claim without stable provenance stays unverified."""
    normalized: list[ConceptEvidence] = []
    for raw in list(items or [])[:12]:
        if not isinstance(raw, dict):
            continue
        concept = str(raw.get("concept") or "").strip()[:120]
        claim = str(raw.get("claim") or "").strip()[:500]
        requested_status = str(raw.get("status") or "insufficient").strip().lower()
        source_id = str(raw.get("source_id") or "").strip()[:160] or None
        record_id = str(raw.get("source_record_id") or "").strip()[:200] or None
        revision = str(raw.get("source_revision") or "").strip()[:120] or None
        observed = str(raw.get("observed_at") or "").strip()[:80] or None
        citation = str(raw.get("citation_id") or "").strip()[:200] or None
        claim_type = str(raw.get("claim_type") or "concept_identity").strip()[:80]
        policy_ok, policy_status = validate_semantic_source_policy(
            raw.get("source_policy"), claim_type=claim_type,
        )
        provenance_complete = all((source_id, record_id, revision, observed, citation, claim))
        if requested_status == "contradictory":
            status = "contradictory"
            claim_status = "contradictory"
        elif requested_status == "resolved" and provenance_complete and policy_ok:
            status = "resolved"
            claim_status = "verified"
        elif requested_status == "unavailable":
            status = "unavailable"
            claim_status = "unverified"
        else:
            status = "insufficient"
            claim_status = "unverified"
        normalized.append(ConceptEvidence(
            concept=concept,
            status=status,
            claim=claim,
            claim_status=claim_status,
            claim_type=claim_type,
            source_id=source_id,
            source_record_id=record_id,
            source_revision=revision,
            observed_at=observed,
            citation_id=citation,
            source_policy_status=policy_status,
        ))
    return tuple(normalized)


def compare_workload_hypotheses(
    hypotheses: Sequence[WorkloadHypothesis],
    evidence: Sequence[ConceptEvidence],
) -> tuple[dict[str, Any], ...]:
    """Measure typed evidence coverage without accepting a proposed hypothesis as fact."""
    accepted_types = {
        str(item.claim_type)
        for item in evidence
        if item.claim_status == "verified" and item.claim_type
    }
    compared: list[dict[str, Any]] = []
    for hypothesis in hypotheses:
        row = hypothesis.model_dump()
        required = set(hypothesis.required_claim_types)
        matched = sorted(required & accepted_types)
        missing = sorted(required - accepted_types)
        if not required:
            status = "not_scored"
        elif not missing:
            status = "covered"
        elif matched:
            status = "partial"
        else:
            status = "unresolved"
        row.update({
            "evidence_coverage": status,
            "matched_claim_types": matched,
            "missing_claim_types": missing,
            "authority": "proposed",
        })
        compared.append(row)
    return tuple(compared)


def reduce_semantic_proposal(
    validation: SemanticValidation,
    *,
    evidence: Sequence[ConceptEvidence] = (),
    authorization_requested: bool = False,
    research_attempted: bool = False,
    research_status: str | None = None,
) -> SemanticDecision:
    """Deterministically accept, research, clarify or reject a semantic proposal."""
    if validation.outcome != "valid" or validation.proposal is None:
        return SemanticDecision(
            outcome="rejected",
            catalog_authority="blocked",
            reasons=validation.reasons or ("semantic_proposal_rejected",),
            state_prevented=("catalog_recommendation", "supplier_enquiry", "commerce_execution"),
            next_permitted_action="repair_semantic_proposal",
            residual_route="ASK",
            residual_reasons=("semantic_proposal_invalid",),
        )
    proposal = validation.proposal
    # Sets have no stable representation order.  A frozenset is the canonical
    # identity for the bounded token comparison and remains deterministic across
    # processes/replays.
    by_concept = {frozenset(_tokens(item.concept)): item for item in evidence}
    unresolved: list[ConceptProposal] = []
    contradictory = False
    for concept in proposal.concepts:
        match = by_concept.get(frozenset(_tokens(concept.text)))
        if match is not None and match.status == "contradictory":
            contradictory = True
        if concept.material and not (match is not None and match.status == "resolved"):
            unresolved.append(concept)

    concepts = tuple(item.model_dump() for item in proposal.concepts)
    questions = tuple(item.model_dump() for item in proposal.evidence_questions if item.material)
    evidence_rows = tuple(item.as_dict() for item in evidence)
    compared_hypotheses = compare_workload_hypotheses(
        proposal.workload_hypotheses, evidence,
    )
    proposal_context = {
        "product_category_candidates": tuple(
            item.model_dump() for item in proposal.product_category_candidates
        ),
        "workload_hypotheses": compared_hypotheses,
        "material_unknowns": tuple(item.model_dump() for item in proposal.material_unknowns),
        "interpretation_confidence": proposal.confidence,
    }
    if contradictory:
        return SemanticDecision(
            outcome="clarify",
            catalog_authority="blocked",
            reasons=("contradictory_concept_evidence",),
            questions=questions,
            concepts=concepts,
            evidence=evidence_rows,
            state_prevented=("catalog_recommendation", "supplier_enquiry", "commerce_execution"),
            next_permitted_action="resolve_evidence_contradiction",
            desired_outcome=proposal.desired_outcome,
            **proposal_context,
            residual_route="ASK",
            residual_reasons=("contradictory_evidence_requires_resolution",),
        )
    if unresolved:
        wants_research = proposal.proposed_action in {"research", "research_then_clarify"}
        outcome = "research" if wants_research and not research_attempted else "clarify"
        residual_reason = (
            "public_verifiable_evidence_required"
            if outcome == "research"
            else (
                "external_research_consent_required"
                if str(research_status or "").strip().lower() == "consent_required"
                else "material_buyer_input_required"
            )
        )
        return SemanticDecision(
            outcome=outcome,
            catalog_authority="blocked",
            reasons=("unresolved_material_concept",),
            questions=questions,
            concepts=concepts,
            evidence=evidence_rows,
            state_prevented=("catalog_recommendation", "supplier_enquiry", "commerce_execution"),
            next_permitted_action=("run_bounded_concept_research" if outcome == "research"
                                   else "ask_material_clarification"),
            desired_outcome=proposal.desired_outcome,
            **proposal_context,
            residual_route="SEARCH" if outcome == "research" else "ASK",
            residual_reasons=(residual_reason,),
        )
    viable_hypotheses = [
        item for item in compared_hypotheses
        if item.get("evidence_coverage") in {"covered", "partial"}
    ]
    buyer_unknown_ids = {
        item.unknown_id for item in proposal.material_unknowns
        if item.resolution_source in {"buyer", "either"}
    }
    discriminating_ids = {
        str(value)
        for item in viable_hypotheses
        for value in list(item.get("discriminating_unknown_ids") or [])
    }
    if len(viable_hypotheses) > 1 and buyer_unknown_ids & discriminating_ids:
        return SemanticDecision(
            outcome="clarify",
            catalog_authority="blocked",
            reasons=("research_discovered_material_ambiguity",),
            questions=questions,
            concepts=concepts,
            evidence=evidence_rows,
            state_prevented=("catalog_recommendation", "supplier_enquiry", "commerce_execution"),
            next_permitted_action="ask_high_value_disambiguation",
            desired_outcome=proposal.desired_outcome,
            **proposal_context,
            residual_route="ASK",
            residual_reasons=("multiple_evidence_supported_hypotheses",),
        )
    residual_route: ResidualRoute = "AUTHORIZE" if authorization_requested else "CONNECTOR"
    return SemanticDecision(
        outcome="proceed_catalog",
        catalog_authority="permitted",
        reasons=("material_concepts_resolved",) if proposal.concepts else ("no_material_ambiguity",),
        questions=(),
        concepts=concepts,
        evidence=evidence_rows,
        state_prevented=(),
        next_permitted_action=(
            "evaluate_consequential_action_policy"
            if authorization_requested else "align_catalog"
        ),
        desired_outcome=proposal.desired_outcome,
        **proposal_context,
        residual_route=residual_route,
        residual_reasons=(
            ("consequential_action_requires_policy",)
            if authorization_requested else ("authoritative_catalog_or_operational_fact_required",)
        ),
    )


def align_catalog(
    decision: SemanticDecision,
    catalog_items: Sequence[dict[str, Any]],
) -> CatalogAlignment:
    """Classify already-retrieved items; never infer an exact fit from product prose."""
    if decision.catalog_authority != "permitted":
        return CatalogAlignment(status="blocked")
    buckets: dict[str, list[str]] = {
        "exact": [], "qualified": [], "alternative": [], "unverified": [],
    }
    for item in list(catalog_items or [])[:100]:
        if not isinstance(item, dict) or not item.get("sku"):
            continue
        status = str(item.get("alignment_status") or "unverified").strip().lower()
        buckets[status if status in buckets else "unverified"].append(str(item["sku"]))
    if buckets["exact"]:
        status = "exact_catalog_match"
    elif buckets["qualified"]:
        status = "qualified_catalog_match"
    elif buckets["alternative"] or buckets["unverified"]:
        status = "no_exact_catalog_match"
    else:
        status = "unsupported"
    actions = (
        ("show_catalog_matches",)
        if status in ("exact_catalog_match", "qualified_catalog_match")
        else (
            "show_qualified_alternatives",
            "supplier_enquiry_after_buyer_commitment",
            "honest_unavailability",
        )
    )
    return CatalogAlignment(
        status=status,
        exact=tuple(buckets["exact"]),
        qualified=tuple(buckets["qualified"]),
        alternatives=tuple(buckets["alternative"]),
        unverified=tuple(buckets["unverified"]),
        permitted_actions=actions,
    )


def approved_narration_evidence(evidence: Sequence[ConceptEvidence]) -> tuple[dict[str, Any], ...]:
    """Return the only concept claims narration may treat as material facts."""
    return tuple(
        item.as_dict() for item in evidence
        if item.status == "resolved" and item.claim_status == "verified" and item.citation_id
    )
