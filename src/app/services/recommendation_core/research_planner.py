"""Compile a validated semantic proposal into a provider-neutral research plan."""

from __future__ import annotations

import os
import re
from typing import Any, Mapping

from src.app.services.recommendation_core.research_contracts import (
    EvidenceNeed,
    MaterialSlot,
    ResearchPlan,
    ResearchQuery,
)


_ID_CLEAN = re.compile(r"[^a-z0-9_]+")


def _bounded_ms(name: str, default: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)) or default)
    except (TypeError, ValueError):
        value = default
    return max(100, min(value, maximum))


def _identifier(value: Any, fallback: str) -> str:
    clean = _ID_CLEAN.sub("_", str(value or "").strip().lower()).strip("_")
    return (clean or fallback)[:64]


def build_research_plan(
    semantic_proposal: Mapping[str, Any] | None,
    *,
    external_research_authorized: bool,
    clarification_answer: Mapping[str, Any] | None = None,
) -> ResearchPlan:
    """Create an executable-shape plan without selecting a provider by name.

    Provider IDs are intentionally absent.  Registry policy later maps each closed
    capability to enrolled providers, keeping the core portable across verticals.
    """
    proposal = semantic_proposal if isinstance(semantic_proposal, Mapping) else {}
    subjects: list[str] = []
    needs: list[EvidenceNeed] = []
    queries: list[ResearchQuery] = []
    hypothesis_ids = [
        _identifier(item.get("hypothesis_id"), f"hypothesis_{index + 1}")
        for index, item in enumerate(list(proposal.get("workload_hypotheses") or [])[:5])
        if isinstance(item, Mapping)
    ]
    for index, raw in enumerate(list(proposal.get("concepts") or [])[:4]):
        if not isinstance(raw, Mapping) or not bool(raw.get("material", True)):
            continue
        # Egress and provider lookup use only the buyer-authored span.  A model's
        # normalized label remains useful in the trace but cannot redirect research.
        subject = " ".join(str(raw.get("query_span") or raw.get("text") or "").split())[:120]
        if not subject:
            continue
        subjects.append(subject)
        identity_need = EvidenceNeed(
            need_id=f"concept_{index + 1}",
            subject_span=subject,
            claim_type="concept_identity",
            provider_capability="concept_discovery",
            max_age_days=365,
        )
        requirements_need = EvidenceNeed(
            need_id=f"requirements_{index + 1}",
            subject_span=subject,
            claim_type="recommended_requirements",
            provider_capability="official_requirements",
            max_age_days=365,
        )
        needs.extend((identity_need, requirements_need))
        # Hypothesis labels are metadata only. They are deliberately excluded from
        # outbound text until an accepted source establishes the terminology.
        queries.extend((
            ResearchQuery(
                query_id=f"identity_{index + 1}",
                evidence_need_id=identity_need.need_id,
                subject_span=subject,
                text=f"{subject} official definition scope",
                strategy="identity",
                hypothesis_ids=hypothesis_ids,
                prohibited_assumptions=[
                    "unverified_vendor", "unverified_product", "invented_hardware_floor",
                ],
            ),
            ResearchQuery(
                query_id=f"requirements_{index + 1}",
                evidence_need_id=requirements_need.need_id,
                subject_span=subject,
                text=f"{subject} official recommended system requirements compatibility",
                strategy="requirements",
                hypothesis_ids=hypothesis_ids,
                prohibited_assumptions=[
                    "unverified_vendor", "unverified_product", "invented_hardware_floor",
                ],
            ),
        ))

    answer = clarification_answer if isinstance(clarification_answer, Mapping) else {}
    answer_qid = _identifier(answer.get("question_id"), "")
    answer_value = " ".join(str(answer.get("value") or "").split())[:500]
    slots: list[MaterialSlot] = []
    for index, raw in enumerate(list(proposal.get("evidence_questions") or [])[:5]):
        if not isinstance(raw, Mapping) or not bool(raw.get("material", True)):
            continue
        question = " ".join(str(raw.get("question") or "").split())[:240]
        if not question:
            continue
        slot_id = _identifier(raw.get("question_id"), f"slot_{index + 1}")
        is_candidate = bool(answer_value and answer_qid and answer_qid == slot_id)
        slots.append(MaterialSlot(
            slot_id=slot_id,
            question=question,
            purpose=str(raw.get("purpose") or "resolve_concept"),
            material=True,
            answer_status="candidate" if is_candidate else "unresolved",
            answer_candidate=answer_value if is_candidate else None,
        ))

    origin = str(proposal.get("proposal_origin") or "model").strip().lower()
    if origin not in {"model", "deterministic_fallback", "persisted"}:
        origin = "model"
    return ResearchPlan(
        interpretation_origin=origin,
        subject_spans=subjects,
        evidence_needs=needs[:8],
        query_bundle=queries[:8],
        material_slots=slots,
        per_provider_timeout_ms=_bounded_ms("RESEARCH_LANE_TIMEOUT_MS", 1800, 30_000),
        total_timeout_ms=_bounded_ms("RESEARCH_TOTAL_TIMEOUT_MS", 2000, 60_000),
        external_research_authorized=bool(external_research_authorized),
    )
