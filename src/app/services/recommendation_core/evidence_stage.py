"""Typed semantic-evidence coordinator for one recommendation turn.

This stage may gather and compile evidence.  It does not mutate response UI,
persist a case, select a product, or authorize a commercial action.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from src.app.services.recommendation_core.requirement_compiler import (
    CompilationResult,
    compile_authoritative_requirements,
)
from src.app.services.recommendation_core.research_trigger_decision import (
    ResearchTriggerDecision,
    decide_research_trigger,
)
from src.app.services.semantic_resolution import (
    SemanticDecision,
    normalize_concept_evidence,
    reduce_semantic_proposal,
    validate_semantic_proposal,
)


@dataclass(frozen=True)
class SemanticEvidenceStageResult:
    semantic_turn_query: str
    evidence_bundle: dict[str, Any]
    concept_data: dict[str, Any]
    normalized_evidence: tuple[Any, ...]
    semantic_decision: SemanticDecision
    compilation: CompilationResult
    catalog_qualifications: tuple[dict[str, Any], ...]
    research_trigger: ResearchTriggerDecision


def resolve_semantic_evidence_stage(
    plan: Any,
    envelope: Any,
    decision: Any,
) -> SemanticEvidenceStageResult:
    """Resolve a material semantic proposal into typed, provenance-bound evidence."""

    # Late binding preserves the provider-replacement seam used by deterministic
    # certification and avoids fixing a transport implementation at import time.
    from src.app.services.evidence_orchestrator import EvidenceBudget, gather_evidence

    raw_semantic = {
        key: value for key, value in plan.semantic_proposal.items()
        if key not in ("validation", "reasons")
    }
    semantic_turn_query = (
        envelope.buyer_query or envelope.query
        if decision.clarification_relation in {"interrupt", "supersede"}
        else envelope.query
    )
    semantic_anchor = (
        str(raw_semantic.get("desired_outcome") or envelope.query)
        if raw_semantic.get("persisted_case_blocker")
        else semantic_turn_query
    )
    if decision.clarification_relation in {"interrupt", "supersede"}:
        raw_semantic["desired_outcome"] = semantic_turn_query
    raw_semantic.pop("persisted_case_blocker", None)
    raw_semantic.pop("state_prevented", None)
    validation = validate_semantic_proposal(raw_semantic, query=semantic_anchor)

    semantic_unknowns = list(raw_semantic.get("material_unknowns") or [])
    semantic_concepts = list(raw_semantic.get("concepts") or [])
    has_material_gap = bool(semantic_unknowns) or any(
        isinstance(item, dict) and bool(item.get("material", True))
        for item in semantic_concepts
    )
    proposal_origin = str(raw_semantic.get("proposal_origin") or "").strip()
    hypotheses = list(raw_semantic.get("workload_hypotheses") or [])
    profile_coverage = (
        "miss" if proposal_origin == "coverage_abstention"
        else "partial" if hypotheses or has_material_gap
        else "unknown"
    )
    research_enabled = str(os.getenv("EXTERNAL_RESEARCH_ENABLED", "0")).strip().lower() in {
        "1", "true", "yes", "on",
    }
    research_trigger = decide_research_trigger(
        interpretation_confidence=float(raw_semantic.get("confidence") or 0.0),
        workload_profile_coverage=profile_coverage,
        corpus_coverage="unknown",
        cache_coverage="unknown",
        material_unknowns=[
            str(item.get("description") or item.get("unknown_id") or "material unknown")
            if isinstance(item, dict) else str(item)
            for item in semantic_unknowns
        ] or [
            str(item.get("text") or "material concept")
            for item in semantic_concepts if isinstance(item, dict)
        ],
        expected_decision_impact=1.0 if has_material_gap else 0.0,
        authorization_state=(
            "granted" if envelope.external_research_consent else "not_requested"
        ),
        external_research_allowed=research_enabled,
    )
    try:
        lane_ms = max(
            100, min(int(os.getenv("RESEARCH_LANE_TIMEOUT_MS", "1800") or 1800), 30_000),
        )
        total_ms = max(
            100, min(int(os.getenv("RESEARCH_TOTAL_TIMEOUT_MS", "2000") or 2000), 60_000),
        )
    except (TypeError, ValueError):
        lane_ms, total_ms = 1800, 2000
    evidence_bundle = gather_evidence(
        plan,
        query=semantic_turn_query,
        uid=envelope.uid,
        tenant_id=envelope.tenant_id,
        web_consent=research_trigger.should_execute_external_research,
        evidence_budget=EvidenceBudget(
            per_lane_ms=lane_ms,
            total_ms=total_ms,
            # concept resolution (3) + governed web discovery (5)
            max_cost_units=8,
        ),
    )
    concept_leg = (evidence_bundle.get("legs") or {}).get("concept_resolution") or {}
    concept_data = dict(concept_leg.get("data") or {})
    rows = concept_data.get("normalized_evidence")
    normalized = tuple(normalize_concept_evidence(rows if isinstance(rows, list) else []))
    semantic_decision = reduce_semantic_proposal(
        validation,
        evidence=list(normalized),
        research_attempted=True,
        research_status=str(concept_data.get("status") or ""),
    )
    compilation = compile_authoritative_requirements(
        item for item in list(concept_data.get("claims") or [])
        if isinstance(item, dict)
    )
    catalog_qualifications = tuple(
        dict(item) for item in (concept_data.get("catalog_qualifications") or [])
        if isinstance(item, dict)
    )[:100]
    return SemanticEvidenceStageResult(
        semantic_turn_query=semantic_turn_query,
        evidence_bundle=evidence_bundle,
        concept_data=concept_data,
        normalized_evidence=normalized,
        semantic_decision=semantic_decision,
        compilation=compilation,
        catalog_qualifications=catalog_qualifications,
        research_trigger=research_trigger,
    )


__all__ = ["SemanticEvidenceStageResult", "resolve_semantic_evidence_stage"]
