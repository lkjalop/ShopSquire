"""Post-result NQE stage for the recommendation route.

This is a strangler-stage extraction from ``routers/recommend.py``. It keeps the
legacy route helpers as injected hooks for now so the first split moves the
inline block without creating router/service import cycles.

ARCHITECTURE NOTE — Core vs Adapter demarcation:
─────────────────────────────────────────────────
CORE (vertical-agnostic):
  • NQE stage orchestration — propose/filter/cap logic, Redis slot persistence.
  • NextQuestionEngine integration — profile-driven question packs (already done).

ADAPTER (product-type-specific):
  • detect_games_in_text() / detect_software_in_text() — electronics-specific
    game/software detection. Phase 2: generalize to profile-driven "domain
    entity detection" (e.g., drug interactions for pharmacy, fabric types for
    fashion).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List

from src.app.flows.catalog import QuestionTemplateCatalog
from src.app.flows.nqe import (
    NQEInput,
    NextQuestionEngine,
    detect_games_in_text,
    detect_software_in_text,
)
from src.app.rag.retrieve import Retriever
from src.app.services.decision_log import log_trace_event
from src.app.services.query_understanding import QueryUnderstanding, build_query_understanding
from src.app.services.recommend_nqe_helpers import build_nqe_asked_and_answered


DOMAIN_REFINEMENT_QUESTION_IDS = {
    "ask_high_school_activity",
    "ask_university_subject",
    "ask_corporate_work_type",
    "ask_gaming_depth",
    "ask_software_confirm",
}


@dataclass
class RecommendStageState:
    query: str | None
    query_effective: str | None
    uid: str
    constraints: Dict[str, Any]
    nlp: Dict[str, Any]
    kv: Dict[str, Any]
    structured_state: Dict[str, Any]
    payload: Dict[str, Any]
    image_context: Dict[str, Any]
    question_plan: Dict[str, Any]
    trace_id: str | None
    flags: Dict[str, Any]
    turn_intent: str | None = None
    followup_explain: bool = False
    shortlist_lock_active: bool = False
    query_understanding: QueryUnderstanding | None = None
    next_questions: List[Dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class RecommendNQEHooks:
    suppress_missing_fields_for_turn_intent: Callable[..., list[str]]
    infer_missing_fields: Callable[..., list[str]]
    resolve_nqe_product_category: Callable[..., str]
    use_case_needs_nqe_refinement: Callable[[Any], bool]
    filter_nqe_questions_by_missing_fields: Callable[..., list[dict]]
    apply_intent_specific_question_bank: Callable[..., list[dict]]
    suppress_nqe_questions_for_turn_intent: Callable[..., list[dict]]
    question_fatigue_filter: Callable[..., tuple[list[dict], list[str]]]
    normalize_recent_nqe_asked: Callable[[Any], list[dict]]
    question_slot_from_id: Callable[[str | None], str]
    append_gpu_disambiguation_question: Callable[..., list[dict]]
    append_standard_nqe_options: Callable[..., list[dict]]
    apply_nqe_confidence_gating: Callable[..., list[dict]]
    apply_persona_confidence_fallback: Callable[..., list[dict]]
    adapt_nqe_questions_for_sentiment: Callable[..., list[dict]]
    dedupe_next_questions_for_render: Callable[[list[dict] | None], list[dict]]
    trace_meta_payload: Callable[..., Dict[str, Any]]


def prioritize_domain_refinement_questions(questions: list[dict] | None) -> list[dict]:
    """Keep specific domain-refinement questions ahead of generic ask_use_case.

    The final render dedupe allows one question per slot. If generic
    ``ask_use_case`` or lower-signal questions arrive first, they can push out
    questions like ``ask_university_subject`` before the two-question cap. Keep
    budget/image guards first, then domain-specific use-case refinements, then
    the remaining generic questions.
    """
    items = [dict(q) for q in (questions or []) if isinstance(q, dict)]
    if not items:
        return []
    guard: list[dict] = []
    domain: list[dict] = []
    generic_use_case: list[dict] = []
    other: list[dict] = []
    guard_ids = {
        "ask_budget",
        "ask_budget_tier",
        "ask_image_budget_mismatch",
        "ask_image_model",
        "reupload_clean_image",
    }
    for q in items:
        qid = str(q.get("id") or "").strip().lower()
        if qid in guard_ids:
            guard.append(q)
        elif qid in DOMAIN_REFINEMENT_QUESTION_IDS:
            domain.append(q)
        elif qid == "ask_use_case":
            generic_use_case.append(q)
        else:
            other.append(q)
    if not domain:
        return items
    return guard + domain + other + generic_use_case


def _header(request: Any, name: str) -> str | None:
    headers = getattr(request, "headers", None)
    if headers is None or not hasattr(headers, "get"):
        return None
    try:
        return headers.get(name)
    except Exception:
        return None


def refine_missing_fields_with_query_understanding(
    legacy_missing_fields: list[str] | None,
    query_understanding: QueryUnderstanding | None,
) -> list[str]:
    """Use QueryUnderstanding to suppress stale NQE gaps without expanding scope.

    The legacy NQE API uses field ids like ``budget`` and ``brand_preference``.
    QueryUnderstanding uses normalized fields like ``budget_max`` and ``brands``.
    For phase 2 migration, only remove a legacy missing field when the unified
    interpretation already has evidence for it; do not add new fields yet.
    """
    legacy = [str(x or "").strip() for x in (legacy_missing_fields or []) if str(x or "").strip()]
    if query_understanding is None:
        return legacy
    missing = {str(x or "").strip() for x in (query_understanding.missing or []) if str(x or "").strip()}
    represented = {
        "budget": "budget_max",
        "use_case": "use_case",
        "brand_preference": "brands",
    }
    out: list[str] = []
    for field in legacy:
        qfield = represented.get(field)
        if qfield and qfield not in missing:
            continue
        out.append(field)
    return out


def _query_understanding_for_state(state: RecommendStageState) -> QueryUnderstanding:
    if state.query_understanding is not None:
        return state.query_understanding
    return build_query_understanding(
        state.query_effective or state.query or "",
        state.constraints if isinstance(state.constraints, dict) else {},
    )


def _persist_nqe_asked(
    *,
    state: RecommendStageState,
    mem: Any,
    hooks: RecommendNQEHooks,
    asked_ids: list[str],
    next_questions: list[dict],
    current_turn: int,
) -> None:
    new_ids = [str(q.get("id") or "") for q in next_questions if isinstance(q, dict) and q.get("id")]
    if not new_ids:
        return
    asked_updated = list(dict.fromkeys(list(asked_ids or []) + new_ids))
    state.structured_state["nqe_asked_ids"] = asked_updated
    state.kv["nqe_asked_ids"] = asked_updated
    recent = hooks.normalize_recent_nqe_asked(
        state.structured_state.get("nqe_recent_asked")
        if isinstance(state.structured_state.get("nqe_recent_asked"), list)
        else state.kv.get("nqe_recent_asked")
    )
    for question in next_questions or []:
        if not isinstance(question, dict) or not question.get("id"):
            continue
        qid = str(question.get("id") or "").strip().lower()
        recent.append(
            {
                "id": qid,
                "slot": hooks.question_slot_from_id(qid),
                "turn": int(current_turn),
            }
        )
    recent = recent[-60:]
    state.structured_state["nqe_recent_asked"] = recent
    state.kv["nqe_recent_asked"] = recent
    if mem is not None:
        mem.set_structured_state(state.uid, state.structured_state)
        mem.set_kv(state.uid, state.kv)


def run_recommend_nqe_stage(
    state: RecommendStageState,
    *,
    hooks: RecommendNQEHooks,
    request: Any,
    mem: Any,
    recent_asked_entries: list[dict] | None,
    current_turn: int,
    fatigue_turns: int,
    contradicted_slots: set[str],
    identity_constraints: Dict[str, Any] | None,
    identity_result: Dict[str, Any] | None,
    use_case_match: str | None,
    image_identity_confidence: float,
    session_context_summary: str | None,
    user_profile_dict: Dict[str, Any] | None,
    gpu_followup_question_needed: bool,
    budget_mismatch_question: Dict[str, Any] | None,
) -> RecommendStageState:
    next_questions: list[dict] = []
    try:
        skip_nqe_clarify = bool(
            str(state.turn_intent or "").upper() == "EXPLAIN"
            or state.followup_explain
            or state.shortlist_lock_active
        )
        query_understanding = _query_understanding_for_state(state)
        missing_fields = hooks.suppress_missing_fields_for_turn_intent(
            hooks.infer_missing_fields(
                constraints=state.constraints,
                nlp=state.nlp if isinstance(state.nlp, dict) else {},
                kv=state.kv if isinstance(state.kv, dict) else None,
            ),
            turn_intent=state.turn_intent,
        )
        missing_fields = refine_missing_fields_with_query_understanding(
            missing_fields,
            query_understanding,
        )
        if missing_fields and not skip_nqe_clarify:
            category = hooks.resolve_nqe_product_category(
                query=state.query,
                constraints=state.constraints,
                identity_constraints=identity_constraints,
                identity_result=identity_result,
            )
            asked_ids, answered = build_nqe_asked_and_answered(
                structured_state=state.structured_state,
                kv=state.kv,
                constraints=state.constraints,
                recent_asked_entries=recent_asked_entries,
                current_turn=current_turn,
                fatigue_turns=fatigue_turns,
                contradicted_slots=contradicted_slots,
                use_case_needs_nqe_refinement=hooks.use_case_needs_nqe_refinement,
            )
            if query_understanding is not None:
                if query_understanding.budget_min is not None and not answered.get("budget_min"):
                    answered["budget_min"] = query_understanding.budget_min
                if query_understanding.budget_max is not None and not answered.get("budget_max"):
                    answered["budget_max"] = query_understanding.budget_max
                if query_understanding.use_case and not answered.get("use_case"):
                    answered["use_case"] = query_understanding.use_case
                if query_understanding.brands and not answered.get("brand_preference"):
                    answered["brand_preference"] = query_understanding.brands[0]

            nqe_input = NQEInput(
                intent="product_search",
                product_category=category,
                symptom=None,
                timeline_days=None,
                risk_score=0.0,
                missing_fields=missing_fields,
                tenant_id=_header(request, "X-Tenant-Id"),
                template_variant=_header(request, "X-NQE-Template-Variant"),
                template_version=_header(request, "X-NQE-Template-Version"),
                trace_id=state.trace_id,
                previously_asked_ids=asked_ids,
                answered_fields=answered,
                has_image=bool(state.image_context.get("labels") or state.image_context.get("ocr")),
                image_identity_confidence=float(image_identity_confidence),
                image_labels=state.image_context.get("labels") or [],
                detected_use_case=use_case_match or (query_understanding.use_case if query_understanding is not None else None),
                query=state.query or "",
                detected_games=detect_games_in_text(state.query or ""),
                detected_software=detect_software_in_text(state.query or ""),
                chat_history_summary=session_context_summary,
                user_profile=user_profile_dict or {},
                turn_intent=state.turn_intent,
                identity_residual_question=state.constraints.get("_identity_residual_question"),
            )
            engine = NextQuestionEngine(Retriever(), QuestionTemplateCatalog())
            next_questions = [q.model_dump() for q in engine.propose(nqe_input)]
            next_questions = hooks.filter_nqe_questions_by_missing_fields(
                next_questions,
                missing_fields=missing_fields,
            )
            next_questions = hooks.apply_intent_specific_question_bank(
                next_questions,
                query=state.query_effective,
                constraints=state.constraints,
            )
            next_questions = prioritize_domain_refinement_questions(next_questions)
            next_questions = hooks.suppress_nqe_questions_for_turn_intent(
                next_questions,
                turn_intent=state.turn_intent,
            )
            next_questions = prioritize_domain_refinement_questions(next_questions)
            next_questions, fatigue_blocked_ids = hooks.question_fatigue_filter(
                next_questions,
                recent_asked=recent_asked_entries,
                current_turn=current_turn,
                window_turns=fatigue_turns,
                contradicted_slots=contradicted_slots,
            )
            if fatigue_blocked_ids:
                try:
                    log_trace_event(
                        trace_id=state.trace_id,
                        event_type="nqe_question_fatigue_guard",
                        source_type="agent",
                        source_id="NQE_Agent",
                        target_type="system",
                        target_id=None,
                        payload={
                            "blocked_question_ids": fatigue_blocked_ids[:10],
                            "window_turns": fatigue_turns,
                            "current_turn": current_turn,
                            "contradicted_slots": sorted(list(contradicted_slots)),
                        },
                    )
                except Exception:
                    pass
            try:
                _persist_nqe_asked(
                    state=state,
                    mem=mem,
                    hooks=hooks,
                    asked_ids=asked_ids,
                    next_questions=next_questions,
                    current_turn=current_turn,
                )
            except Exception:
                pass

            next_questions = prioritize_domain_refinement_questions(next_questions)
            next_questions = (next_questions or [])[:2]
            if gpu_followup_question_needed:
                next_questions = hooks.append_gpu_disambiguation_question(
                    next_questions,
                    state.query_effective,
                )
            try:
                if budget_mismatch_question and not any(
                    str((q or {}).get("id") or "") == "ask_image_budget_mismatch"
                    for q in (next_questions or [])
                ):
                    next_questions = [budget_mismatch_question] + (next_questions or [])
                    next_questions = next_questions[:2]
            except Exception:
                pass
            next_questions = hooks.suppress_nqe_questions_for_turn_intent(
                next_questions,
                turn_intent=state.turn_intent,
            )
            next_questions = hooks.append_standard_nqe_options(next_questions, state.query_effective)
            next_questions = hooks.apply_nqe_confidence_gating(
                next_questions,
                query=state.query_effective,
                confidence_band=state.question_plan.get("confidence_band"),
            )
            next_questions = hooks.apply_persona_confidence_fallback(
                next_questions,
                persona=state.constraints.get("buyer_persona") or state.constraints.get("buyer_persona_candidate"),
                persona_confidence=state.constraints.get("buyer_persona_confidence"),
            )
            next_questions = hooks.adapt_nqe_questions_for_sentiment(
                next_questions,
                sentiment=str(state.nlp.get("sentiment") or "neutral"),
            )
            next_questions = prioritize_domain_refinement_questions(next_questions)
            next_questions = hooks.dedupe_next_questions_for_render(next_questions)
            if next_questions:
                state.payload["next_questions"] = next_questions
                try:
                    if isinstance(state.nlp, dict):
                        state.nlp.setdefault("followups", [])
                        for question in next_questions:
                            if question not in state.nlp["followups"]:
                                state.nlp["followups"].append(question)
                except Exception:
                    pass
                try:
                    log_trace_event(
                        trace_id=state.trace_id,
                        event_type="nqe_question_shown",
                        source_type="agent",
                        source_id="NQE_Agent",
                        target_type="user",
                        target_id=None,
                        payload={
                            "intent": "product_search",
                            "category": category,
                            "missing_fields": missing_fields,
                            "questions": next_questions,
                            **hooks.trace_meta_payload(
                                policy_version=state.flags.get("POLICY_VERSION", "v1"),
                                context_ids=["nqe_templates"],
                            ),
                        },
                    )
                    log_trace_event(
                        trace_id=state.trace_id,
                        event_type="next_questions",
                        source_type="agent",
                        source_id="NQE_Agent",
                        target_type="user",
                        target_id=None,
                        payload={
                            "intent": "product_search",
                            "category": category,
                            "missing_fields": missing_fields,
                            "questions": next_questions,
                            **hooks.trace_meta_payload(
                                policy_version=state.flags.get("POLICY_VERSION", "v1"),
                                context_ids=["nqe_templates"],
                            ),
                        },
                    )
                except Exception:
                    pass
    except Exception:
        next_questions = []

    if gpu_followup_question_needed:
        next_questions = hooks.append_gpu_disambiguation_question(next_questions, state.query_effective)
        state.payload["next_questions"] = next_questions
    if isinstance(state.payload.get("next_questions"), list):
        state.payload["next_questions"] = hooks.append_standard_nqe_options(
            state.payload.get("next_questions"),
            state.query_effective,
        )
        state.payload["next_questions"] = hooks.apply_nqe_confidence_gating(
            state.payload.get("next_questions"),
            query=state.query_effective,
            confidence_band=state.question_plan.get("confidence_band"),
        )
        state.payload["next_questions"] = hooks.apply_persona_confidence_fallback(
            state.payload.get("next_questions"),
            persona=state.constraints.get("buyer_persona") or state.constraints.get("buyer_persona_candidate"),
            persona_confidence=state.constraints.get("buyer_persona_confidence"),
        )
        state.payload["next_questions"] = prioritize_domain_refinement_questions(
            state.payload.get("next_questions")
        )
        state.payload["next_questions"] = hooks.dedupe_next_questions_for_render(
            state.payload.get("next_questions")
        )
    if (
        str(state.turn_intent or "").upper() in {"SEARCH", "FILTER"}
        and not state.followup_explain
        and not isinstance(state.payload.get("next_questions"), list)
    ):
        state.payload["next_questions"] = []
    if (
        str(state.turn_intent or "").upper() in {"SEARCH", "FILTER"}
        and not state.followup_explain
        and isinstance(state.payload.get("next_questions"), list)
        and len(state.payload.get("next_questions") or []) == 0
    ):
        state.payload["next_questions"] = [
            {
                "id": "ask_use_case",
                "text": "What will you primarily use it for (notes, office, coding, gaming, video editing, AI)?",
                "goal": "clarify_use_case",
                "options": [
                    {"id": "uc_notes", "label": "Notes / Office"},
                    {"id": "uc_coding", "label": "Coding / Engineering"},
                    {"id": "uc_gaming", "label": "Gaming / Creative"},
                ],
            }
        ]
    state.next_questions = list(state.payload.get("next_questions") or next_questions or [])
    return state
