"""
═══════════════════════════════════════════════════════════════════════════
recommend_memory_writeback — CORE (vertical-agnostic)
═══════════════════════════════════════════════════════════════════════════
End-of-turn memory persistence for the recommend pipeline.

Extracted from recommend.py suggest() tail (the single large try/except block
that saves kv_out, structured_state_out, product_memory_bank, confirmed_slots,
NQE asked tracking, and rolling-summary checkpoints).

All functions here are pure/side-effect-isolated and do not reference any
electronics-specific constants or brand patterns.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from src.app.deps import scrub_pii
from src.app.services.recommend_nqe_helpers import (
    normalize_recent_nqe_asked,
    question_slot_from_id,
)


# ─── Pure helpers (moved from recommend.py) ──────────────────────────────────


def build_envelope_snapshot(
    *,
    constraints: Dict[str, Any],
    candidates_count: int,
    results_count: int,
    shortlist_locked: bool,
    shortlist_size: int,
) -> Dict[str, Any]:
    return {
        "budget_min": constraints.get("budget_min"),
        "budget_max": constraints.get("budget_max"),
        "brands": list(constraints.get("brands") or []),
        "specs": list(constraints.get("specs") or []),
        "candidates_count": int(candidates_count),
        "results_count": int(results_count),
        "shortlist_locked": bool(shortlist_locked),
        "shortlist_size": int(shortlist_size),
    }


def update_pinned_context(
    *,
    kv: Dict[str, Any],
    constraints: Dict[str, Any],
    shortlist_skus: list[str] | None,
    turn_type: str,
    ts: int | None = None,
) -> Dict[str, Any]:
    now_ts = int(ts or time.time())
    pinned = kv.get("pinned_context") if isinstance(kv.get("pinned_context"), dict) else {}

    def _pin(key: str, value: Any) -> None:
        if value is None:
            return
        if isinstance(value, list) and not value:
            return
        pinned[key] = {"value": value, "ts": now_ts, "source_turn_type": turn_type}

    _pin("budget", {"min": constraints.get("budget_min"), "max": constraints.get("budget_max")})
    _pin("use_case", constraints.get("use_case"))
    _pin("gpu_preference", constraints.get("gpu_preference"))
    _pin("brand_preference", list(constraints.get("brands") or []))
    if shortlist_skus:
        _pin("selected_skus", shortlist_skus[:12])
    excludes = list(constraints.get("brand_excludes") or [])
    if excludes:
        _pin("excluded_skus", excludes[:12])
    kv["pinned_context"] = pinned
    return kv


def build_rolling_summary(
    *,
    kv: Dict[str, Any],
    constraints: Dict[str, Any],
    results: list[dict] | None,
    next_questions: list[dict] | None,
    turn_type: str,
    referents: Dict[str, Any] | None,
) -> Dict[str, Any]:
    pinned = kv.get("pinned_context") if isinstance(kv.get("pinned_context"), dict) else {}
    current_shortlist = [str((r or {}).get("sku") or "") for r in (results or []) if isinstance(r, dict)]
    current_shortlist = [x for x in current_shortlist if x][:12]
    unresolved = []
    for q in (next_questions or []):
        if isinstance(q, dict) and q.get("text"):
            unresolved.append(str(q.get("text")))
    unresolved = unresolved[:4]
    goals = []
    if constraints.get("use_case"):
        goals.append(str(constraints.get("use_case")))
    if constraints.get("budget_max") is not None or constraints.get("budget_min") is not None:
        goals.append("budget_focused")
    summary = {
        "ts": int(time.time()),
        "turn_type": turn_type,
        "goals": goals[:3],
        "hard_constraints": {
            "budget_min": constraints.get("budget_min"),
            "budget_max": constraints.get("budget_max"),
            "brands": list(constraints.get("brands") or [])[:8],
            "gpu_preference": constraints.get("gpu_preference"),
        },
        "soft_preferences": {
            "specs": list(constraints.get("specs") or [])[:10],
            "use_case_tags": list(constraints.get("use_case_tags") or [])[:8],
        },
        "current_shortlist": current_shortlist,
        "pinned_context": pinned,
        "referents": referents or {"has_reference": False, "source": "none", "skus": []},
        "unresolved_questions": unresolved,
    }
    return summary


# ─── Orchestrator ────────────────────────────────────────────────────────────


@dataclass
class TurnPersistenceInput:
    """All inputs needed for end-of-turn memory persistence."""
    uid: str
    query: str
    constraints: Dict[str, Any]
    results: List[Dict[str, Any]]
    payload: Dict[str, Any]  # mutated in-place (adds session_summary)
    kv: Dict[str, Any]
    structured_state: Dict[str, Any]
    product_memory_bank: Dict[str, Any]
    image_context: Dict[str, Any]
    trace_id: str
    turn_type: str
    turn_intent: str
    referents: Dict[str, Any]
    followup_contract: Dict[str, Any]
    intent_execution_plan: Optional[Dict[str, Any]]
    candidates: List[Dict[str, Any]]
    shortlist_lock_active: bool
    llm_model: str
    assistant_message: Optional[str]
    flags: Dict[str, Any]
    ctx_summary: Optional[Dict[str, Any]]  # ctx.get("summary") from memory context


@dataclass
class TurnPersistenceHooks:
    """Callbacks injected from the route to avoid circular imports."""
    mem: Any  # Memory service instance
    suggest_ctx: Any  # SuggestContext — gets kv_out/structured_state_out bound
    log_trace_event: Callable[..., None]
    trace_meta_payload: Callable[..., Dict[str, Any]]


def persist_turn_state(inp: TurnPersistenceInput, hooks: TurnPersistenceHooks) -> None:
    """Persist all end-of-turn state (kv, structured_state, product_memory_bank, summary).

    Mutates ``inp.payload`` in-place (adds ``session_summary`` on checkpoint turns).
    Binds ``hooks.suggest_ctx.kv_out`` and ``hooks.suggest_ctx.structured_state_out``.
    Never raises — mirrors the original try/except: pass contract.
    """
    try:
        _persist_turn_state_inner(inp, hooks)
    except Exception:
        pass


def _persist_turn_state_inner(inp: TurnPersistenceInput, hooks: TurnPersistenceHooks) -> None:
    mem = hooks.mem
    _ctx = hooks.suggest_ctx

    shortlist_skus = [str((r or {}).get("sku") or "") for r in (inp.results or []) if isinstance(r, dict)]
    shortlist_skus = [s for s in shortlist_skus if s][:12]

    kv_out = mem.get_kv(inp.uid) or {}
    if not kv_out and isinstance(inp.kv, dict):
        kv_out = dict(inp.kv)
    structured_state_out = mem.get_structured_state(inp.uid) or {}
    product_memory_bank_out = dict(inp.product_memory_bank or {})

    # Only overwrite the shortlist when this turn produced results.
    if shortlist_skus:
        kv_out["last_shortlist_skus"] = shortlist_skus
        kv_out["last_valid_shortlist_skus"] = shortlist_skus
        structured_state_out["last_shortlist_skus"] = shortlist_skus
        structured_state_out["last_valid_shortlist_skus"] = shortlist_skus

    kv_out["last_constraints_snapshot"] = {
        "budget_min": inp.constraints.get("budget_min"),
        "budget_max": inp.constraints.get("budget_max"),
        "brands": list(inp.constraints.get("brands") or []),
        "specs": list(inp.constraints.get("specs") or []),
    }
    structured_state_out["last_constraints_snapshot"] = dict(kv_out["last_constraints_snapshot"])

    if inp.turn_type in {"result_turn", "constraint_update_turn"}:
        kv_out["last_valid_constraints_snapshot"] = dict(kv_out["last_constraints_snapshot"])
        structured_state_out["last_valid_constraints_snapshot"] = dict(kv_out["last_constraints_snapshot"])

    kv_out["last_result_envelope"] = build_envelope_snapshot(
        constraints=inp.constraints,
        candidates_count=len(inp.candidates or []),
        results_count=len(inp.results or []),
        shortlist_locked=inp.shortlist_lock_active,
        shortlist_size=len(shortlist_skus),
    )
    structured_state_out["last_result_envelope"] = dict(kv_out["last_result_envelope"])

    kv_out["last_turn_type"] = inp.turn_type
    kv_out["last_turn_intent"] = inp.turn_intent
    kv_out["last_referents"] = inp.referents
    kv_out["last_followup_contract"] = inp.followup_contract
    kv_out["last_intent_execution_plan"] = inp.intent_execution_plan
    structured_state_out["last_turn_type"] = inp.turn_type
    structured_state_out["last_turn_intent"] = inp.turn_intent
    structured_state_out["last_referents"] = inp.referents
    structured_state_out["last_followup_contract"] = inp.followup_contract
    structured_state_out["last_intent_execution_plan"] = inp.intent_execution_plan

    structured_state_out["nqe_asked_ids"] = list(
        kv_out.get("nqe_asked_ids") or structured_state_out.get("nqe_asked_ids") or []
    )
    structured_state_out["nqe_answered_fields"] = dict(
        kv_out.get("nqe_answered_fields") or structured_state_out.get("nqe_answered_fields") or {}
    )
    structured_state_out["nqe_recent_asked"] = normalize_recent_nqe_asked(
        kv_out.get("nqe_recent_asked")
        if isinstance(kv_out.get("nqe_recent_asked"), list)
        else structured_state_out.get("nqe_recent_asked")
    )

    kv_out = update_pinned_context(
        kv=kv_out,
        constraints=inp.constraints,
        shortlist_skus=shortlist_skus,
        turn_type=inp.turn_type,
    )

    # SuggestContext adoption: bind finalized memory write-back dicts
    _ctx.kv_out = kv_out
    _ctx.structured_state_out = structured_state_out

    # Confirmed slots consolidation
    confirmed_slots_out = (
        kv_out.get("confirmed_slots")
        if isinstance(kv_out.get("confirmed_slots"), dict)
        else structured_state_out.get("confirmed_slots")
    )
    confirmed_slots_out = dict(confirmed_slots_out or {})
    for _key in ("budget_min", "budget_max", "use_case", "gpu_preference", "availability", "condition"):
        _val = inp.constraints.get(_key)
        if _val is not None:
            confirmed_slots_out[_key] = _val
    if inp.constraints.get("brands"):
        confirmed_slots_out["brands"] = list(inp.constraints.get("brands") or [])[:8]
    if inp.constraints.get("specs"):
        confirmed_slots_out["specs"] = list(inp.constraints.get("specs") or [])[:12]
    if inp.constraints.get("brand_excludes"):
        confirmed_slots_out["brand_excludes"] = list(inp.constraints.get("brand_excludes") or [])[:12]
    if inp.constraints.get("use_case_tags"):
        confirmed_slots_out["use_case_tags"] = list(inp.constraints.get("use_case_tags") or [])[:12]
    kv_out["confirmed_slots"] = confirmed_slots_out
    structured_state_out["confirmed_slots"] = dict(confirmed_slots_out)

    # Image context persistence
    if (
        inp.image_context.get("labels")
        or inp.image_context.get("ocr")
        or inp.image_context.get("hash")
        or inp.image_context.get("intent")
    ):
        kv_out["image_context"] = {
            "hash": inp.image_context.get("hash"),
            "intent": inp.image_context.get("intent"),
            "labels": list(inp.image_context.get("labels") or [])[:12],
            "ocr": str(inp.image_context.get("ocr") or "")[:500],
            "ts": int(time.time()),
        }
        structured_state_out["image_context"] = dict(kv_out["image_context"])

    kv_out["conversation_turn"] = int(kv_out.get("conversation_turn") or 0) + 1
    structured_state_out["conversation_turn"] = int(kv_out["conversation_turn"])

    # NQE asked tracking
    if isinstance(inp.payload.get("next_questions"), list) and inp.payload.get("next_questions"):
        asked = kv_out.get("nqe_asked") if isinstance(kv_out.get("nqe_asked"), list) else []
        asked_recent = normalize_recent_nqe_asked(
            kv_out.get("nqe_recent_asked")
            if isinstance(kv_out.get("nqe_recent_asked"), list)
            else structured_state_out.get("nqe_recent_asked")
        )
        for q in inp.payload.get("next_questions") or []:
            if isinstance(q, dict) and q.get("id"):
                qid = str(q.get("id"))
                if qid not in asked:
                    asked.append(qid)
                asked_recent.append(
                    {
                        "id": str(qid).strip().lower(),
                        "slot": question_slot_from_id(qid),
                        "turn": int(kv_out.get("conversation_turn") or 0) + 1,
                    }
                )
        kv_out["nqe_asked"] = asked[-25:]
        structured_state_out["nqe_asked"] = list(kv_out["nqe_asked"])
        kv_out["nqe_recent_asked"] = asked_recent[-60:]
        structured_state_out["nqe_recent_asked"] = list(kv_out["nqe_recent_asked"])

    # Product memory bank
    hist = list(product_memory_bank_out.get("recent_recommendations") or [])
    hist.append({
        "ts": int(time.time()),
        "query": scrub_pii(inp.query or "")[:300],
        "shortlist_skus": shortlist_skus,
        "budget_min": inp.constraints.get("budget_min"),
        "budget_max": inp.constraints.get("budget_max"),
        "turn_type": inp.turn_type,
        "trace_id": inp.trace_id,
    })
    product_memory_bank_out["recent_recommendations"] = hist[-20:]
    product_memory_bank_out["last_trace_id"] = inp.trace_id
    product_memory_bank_out["last_query"] = scrub_pii(inp.query or "")[:300]
    if shortlist_skus:
        product_memory_bank_out["last_shortlist_skus"] = shortlist_skus

    # Persist to memory service
    active_ttl = int(os.getenv("CHAT_ACTIVE_TTL_SECONDS", "86400"))
    mem.set_kv(inp.uid, kv_out, ttl_seconds=active_ttl)
    mem.set_structured_state(inp.uid, structured_state_out, ttl_seconds=active_ttl)
    mem.set_product_memory_bank(inp.uid, product_memory_bank_out, ttl_seconds=active_ttl)
    mem.touch_session(inp.uid, ttl_seconds=active_ttl)

    # Summary checkpoint
    summary_interval = int(os.getenv("MEMORY_SUMMARY_INTERVAL", "10"))
    should_checkpoint = bool(
        (int(kv_out.get("conversation_turn") or 0) % max(1, summary_interval) == 0)
        or inp.turn_type in {"zero_result_turn", "explain_turn"}
        or not isinstance(inp.ctx_summary, dict)
    )
    if should_checkpoint:
        rolling_summary = build_rolling_summary(
            kv=kv_out,
            constraints=inp.constraints,
            results=inp.results or [],
            next_questions=(
                inp.payload.get("next_questions")
                if isinstance(inp.payload.get("next_questions"), list)
                else []
            ),
            turn_type=inp.turn_type,
            referents=inp.referents,
        )
        mem.set_summary(inp.uid, rolling_summary, ttl_seconds=active_ttl)
        inp.payload["session_summary"] = rolling_summary

        # Persist a typed Episode
        try:
            from src.app.services.episodic_memory import EpisodicMemory as _EpisodicMemory
            _ep_mem = _EpisodicMemory(mem)
            _ep_skus = [str(r.get("sku") or "") for r in (inp.results or []) if isinstance(r, dict)][:6]
            _ep_slots = {
                k: inp.constraints[k]
                for k in ("budget_max", "budget_min", "use_case", "brands", "gpu_preference")
                if k in inp.constraints and inp.constraints[k] is not None
            }
            _ep_response_text = str(inp.assistant_message or "")[:120] or inp.turn_type
            _ep_mem.save_episode(
                inp.uid,
                turn_index=int(kv_out.get("conversation_turn") or 0),
                query=str(inp.query or "")[:200],
                response_summary=_ep_response_text,
                slots_captured=_ep_slots,
                products_shown=_ep_skus,
                model_used=str(inp.llm_model or ""),
            )
        except Exception:
            pass

        hooks.log_trace_event(
            trace_id=inp.trace_id,
            event_type="session_summary_checkpoint",
            source_type="agent",
            source_id="Conversation_Memory_Agent",
            target_type="system",
            target_id=None,
            payload={
                "turn": int(kv_out.get("conversation_turn") or 0),
                "turn_type": inp.turn_type,
                "summary": rolling_summary,
                **hooks.trace_meta_payload(
                    policy_version=inp.flags.get("POLICY_VERSION", "v1"),
                    context_ids=["session_summary", "pinned_context"],
                ),
            },
        )
