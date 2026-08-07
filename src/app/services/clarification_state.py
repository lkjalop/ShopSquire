"""Typed, vertical-neutral clarification state for conversational commerce.

The model may propose a material question. This module owns the bounded state and
answer contract; it does not interpret product vocabulary or authorize an action.
"""

from __future__ import annotations

import time
import re
from dataclasses import asdict, dataclass
from typing import Any, Literal, Mapping


ClarificationRelation = Literal[
    "none", "pending", "answer", "interrupt", "supersede", "ambiguous", "expired"
]

_INTERRUPTING_LANES = frozenset({
    "POLICY_QUESTION",
    "SUPPORT_CLAIM",
    "INVENTORY",
})

_RESEARCH_CONSENT_DENIAL = re.compile(
    r"\b(?:do\s+not|don't|dont|cannot|can't|without)\b.{0,30}\b(?:research|search|check|look\s*up)\b",
    re.IGNORECASE,
)
_RESEARCH_CONSENT_GRANT = re.compile(
    r"(?:\b(?:you\s+may|you\s+can|please|yes[, ]*please|i\s+(?:consent|authorize|approve))\b"
    r".{0,50}\b(?:research|search|check|look\s*up)\b|"
    r"\b(?:research|search|check|look\s*up)\b.{0,50}\b(?:approved|official|vendor)\s+sources?\b)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ClarificationTurnResult:
    effective_query: str
    relation: ClarificationRelation
    consume_pending: bool = False
    suspend_pending: bool = False
    answer: str | None = None
    question_id: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _short(value: Any, maximum: int) -> str:
    return " ".join(str(value or "").split())[:maximum]


def external_research_consent_granted(query: str) -> bool:
    """Recognize explicit per-turn research permission from buyer-authored text.

    Consent is consequential input, so this intentionally accepts only an
    affirmative permission phrase and rejects a nearby explicit denial.  The
    model may interpret what to research; it cannot manufacture consent.
    """
    text = _short(query, 1_000)
    if not text or _RESEARCH_CONSENT_DENIAL.search(text):
        return False
    return bool(_RESEARCH_CONSENT_GRANT.search(text))


def replacement_root_query(
    *,
    pending: Mapping[str, Any] | None,
    submitted_query: str,
    clarification_relation: str | None,
) -> str:
    """Keep one buyer objective across a chain of material clarifications.

    A model-labeled supersede starts a new objective. Answers, interruptions and
    fallback-safe pending turns retain the original buyer request; the latest
    answer is evidence for that request, not a replacement for it.
    """
    state = pending if isinstance(pending, Mapping) else {}
    relation = _short(clarification_relation, 40).lower()
    if state and relation != "supersede":
        original = _short(state.get("original_query"), 1_000)
        if original:
            return original
    return _short(submitted_query, 1_000)


def build_pending_clarification(
    question: Mapping[str, Any],
    *,
    original_query: str,
    trace_id: str | None,
    semantic_resolution: Mapping[str, Any] | None = None,
    case_anchor: Mapping[str, Any] | None = None,
    external_research_consent: bool = False,
    commercial_state: Mapping[str, Any] | None = None,
    original_intent: str | None = None,
    now_epoch: int | None = None,
    ttl_seconds: int = 900,
) -> dict[str, Any]:
    """Build a bounded persistence record from any material question."""
    now = int(time.time() if now_epoch is None else now_epoch)
    ttl = max(30, min(int(ttl_seconds), 3_600))
    options: list[dict[str, str]] = []
    for raw in list(question.get("options") or [])[:8]:
        if not isinstance(raw, Mapping):
            continue
        option_id = _short(raw.get("id"), 80).lower()
        if not option_id:
            continue
        options.append({
            "id": option_id,
            "label": _short(raw.get("label") or raw.get("text") or option_id, 160),
            "value": _short(raw.get("value") or raw.get("label") or option_id, 240),
        })
    semantic = semantic_resolution if isinstance(semantic_resolution, Mapping) else {}
    anchor = case_anchor if isinstance(case_anchor, Mapping) else {}
    commercial = commercial_state if isinstance(commercial_state, Mapping) else {}
    semantic_context = {
        "desired_outcome": _short(semantic.get("desired_outcome"), 240) or None,
        "catalog_authority": (
            "blocked" if semantic.get("catalog_authority") == "blocked" else "unknown"
        ),
        "concepts": [
            dict(item) for item in list(semantic.get("concepts") or [])[:4]
            if isinstance(item, Mapping)
        ],
        "product_category_candidates": [
            dict(item)
            for item in list(semantic.get("product_category_candidates") or [])[:5]
            if isinstance(item, Mapping)
        ],
        "workload_hypotheses": [
            dict(item)
            for item in list(semantic.get("workload_hypotheses") or [])[:5]
            if isinstance(item, Mapping)
        ],
        "material_unknowns": [
            dict(item)
            for item in list(semantic.get("material_unknowns") or [])[:8]
            if isinstance(item, Mapping)
        ],
        "questions": [
            dict(item) for item in list(semantic.get("questions") or [])[:5]
            if isinstance(item, Mapping)
        ],
        "state_prevented": [
            _short(item, 80) for item in list(semantic.get("state_prevented") or [])[:8]
            if _short(item, 80)
        ],
        "next_permitted_action": _short(
            semantic.get("next_permitted_action"), 120
        ) or None,
    }
    bounded_commercial = {
        "quantity": commercial.get("quantity"),
        "total_budget_cents": commercial.get("total_budget_cents"),
        "currency": _short(commercial.get("currency"), 8).upper() or None,
        "selected_sku": _short(commercial.get("selected_sku"), 120) or None,
    }
    return {
        "version": 2,
        "state": "active",
        "question_id": _short(question.get("id") or question.get("question_id"), 80).lower(),
        "question": _short(question.get("text") or question.get("question"), 300),
        "purpose": _short(question.get("goal") or question.get("purpose") or "resolve_concept", 80),
        "reason": _short(question.get("reason") or "material_clarification", 120),
        "answer_mode": "enum" if options else "free_text",
        "options": options,
        "allowed_option_ids": [item["id"] for item in options],
        "original_query": _short(original_query, 1_000),
        "original_intent": _short(original_intent, 40).upper() or None,
        "trace_id": _short(trace_id, 160) or None,
        "case_id": _short(anchor.get("case_id"), 240) or None,
        "desired_outcome": _short(semantic.get("desired_outcome"), 240) or None,
        "semantic_context": semantic_context,
        "external_research_consent": bool(external_research_consent),
        "commercial_context": bounded_commercial,
        "created_at": now,
        "expires_at": now + ttl,
    }


def _option_answer(
    selection: Mapping[str, Any], pending: Mapping[str, Any]
) -> str | None:
    selected_qid = _short(selection.get("question_id"), 80).lower()
    selected_oid = _short(selection.get("option_id"), 80).lower()
    pending_qid = _short(pending.get("question_id"), 80).lower()
    if not selected_qid or selected_qid != pending_qid or not selected_oid:
        return None
    for option in list(pending.get("options") or [])[:8]:
        if not isinstance(option, Mapping):
            continue
        if _short(option.get("id"), 80).lower() == selected_oid:
            return _short(
                selection.get("option_value")
                or option.get("label")
                or option.get("value")
                or selected_oid,
                240,
            )
    return None


def _merged_query(original_query: str, question: str, answer: str) -> str:
    # The annotation remains buyer-visible text, not hidden instructions. The model
    # still reinterprets the complete turn and deterministic clamps re-authorize it.
    return (
        f"{_short(original_query, 1_000)} "
        f"Buyer clarification to '{_short(question, 240)}': {_short(answer, 300)}."
    ).strip()


def _research_consent_query(original_query: str, *, granted: bool) -> str:
    decision = (
        "Buyer authorized bounded research from approved official sources."
        if granted
        else "Buyer declined external research."
    )
    return f"{_short(original_query, 1_000)} {decision}".strip()


def reduce_clarification_turn(
    *,
    query: str,
    nqe_selection: Mapping[str, Any] | None,
    pending: Mapping[str, Any] | None,
    intent_hint: str | None = None,
    now_epoch: int | None = None,
) -> ClarificationTurnResult:
    """Reduce one buyer turn against pending state without product semantics.

    Free-text answers to open questions are left for the bounded turn interpreter;
    enum selections and budget-scope grammar can be accepted without another model.
    """
    current = _short(query, 1_000)
    state = pending if isinstance(pending, Mapping) else {}
    question_id = _short(state.get("question_id"), 80).lower() or None
    if not question_id or str(state.get("state") or "active") not in {"active", "suspended"}:
        return ClarificationTurnResult(current, "none")

    now = int(time.time() if now_epoch is None else now_epoch)
    try:
        expires_at = int(state.get("expires_at") or 0)
    except (TypeError, ValueError):
        expires_at = 0
    if expires_at and now > expires_at:
        return ClarificationTurnResult(
            current, "expired", consume_pending=True, question_id=question_id,
        )

    lane = _short(intent_hint, 40).upper()
    if lane in _INTERRUPTING_LANES:
        return ClarificationTurnResult(
            current,
            "interrupt",
            suspend_pending=True,
            question_id=question_id,
        )

    selection = nqe_selection if isinstance(nqe_selection, Mapping) else {}
    answer = _option_answer(selection, state)
    if answer:
        selected_oid = _short(selection.get("option_id"), 80).lower()
        if question_id == "external_research_consent":
            granted = selected_oid in {"approve", "approved", "allow", "yes"}
            return ClarificationTurnResult(
                _research_consent_query(
                    _short(state.get("original_query"), 1_000), granted=granted,
                ),
                "answer",
                consume_pending=True,
                answer="approved" if granted else "declined",
                question_id=question_id,
            )
        if question_id == "budget_scope" and selected_oid in {"total", "per_unit"}:
            statement = (
                "The stated budget is the total budget for all requested units."
                if selected_oid == "total"
                else "The stated budget is a per item budget."
            )
            return ClarificationTurnResult(
                f"{_short(state.get('original_query'), 1_000)} {statement}".strip(),
                "answer",
                consume_pending=True,
                answer=selected_oid,
                question_id=question_id,
            )
        return ClarificationTurnResult(
            _merged_query(
                _short(state.get("original_query"), 1_000),
                _short(state.get("question"), 300),
                answer,
            ),
            "answer",
            consume_pending=True,
            answer=answer,
            question_id=question_id,
        )
    if selection:
        return ClarificationTurnResult(current, "ambiguous", question_id=question_id)

    if question_id == "external_research_consent" and external_research_consent_granted(current):
        return ClarificationTurnResult(
            _research_consent_query(
                _short(state.get("original_query"), 1_000), granted=True,
            ),
            "answer",
            consume_pending=True,
            answer="approved",
            question_id=question_id,
        )

    if question_id == "budget_scope":
        try:
            from src.app.services.budget_grammar import classify_budget_scope

            scope = classify_budget_scope(current)
        except Exception:
            scope = "unknown"
        if scope in {"total", "per_unit"}:
            statement = (
                "The stated budget is the total budget for all requested units."
                if scope == "total"
                else "The stated budget is a per item budget."
            )
            return ClarificationTurnResult(
                f"{_short(state.get('original_query'), 1_000)} {statement}".strip(),
                "answer",
                consume_pending=True,
                answer=scope,
                question_id=question_id,
            )

    # Open-text material answers remain model-interpreted, but the interpreter must
    # see the objective and question they are answering. This is context transport,
    # not acceptance: pending state remains until the bounded router labels the
    # relationship as answer, interrupt, supersede, or ambiguous.
    return ClarificationTurnResult(
        _merged_query(
            _short(state.get("original_query"), 1_000),
            _short(state.get("question"), 300),
            current,
        ),
        "pending",
        answer=current or None,
        question_id=question_id,
    )
