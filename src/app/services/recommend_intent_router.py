"""
═══════════════════════════════════════════════════════════════════════════
recommend_intent_router — CORE (vertical-agnostic)
═══════════════════════════════════════════════════════════════════════════
Ollama/rule-based intent routing for the recommend pipeline.

Extracted from recommend.py suggest() — the block that determines whether
to call the LLM for intent classification or fall back to deterministic
rule-based routing, respecting the staged rollout (off/shadow/percent/full).
"""
from __future__ import annotations

import hashlib
import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

import httpx

from src.app.services.llm_provider import (
    OLLAMA_URL,
    complexity_explain,
    is_complex_query,
    select_ollama_model,
)


# ─── Helpers ─────────────────────────────────────────────────────────────────


def stable_rollout_bucket(seed: str | None) -> int:
    s = str(seed or "").strip()
    if not s:
        s = "default"
    return int(hashlib.sha256(s.encode("utf-8")).hexdigest(), 16) % 100


def resolve_ollama_intent_rollout(
    flags: Dict[str, Any], *, uid: str, trace_id: str | None
) -> Dict[str, Any]:
    cfg = (
        flags.get("OLLAMA_INTENT_ROUTING")
        if isinstance(flags.get("OLLAMA_INTENT_ROUTING"), dict)
        else {}
    )
    stage = str(cfg.get("stage") or "").strip().lower()
    if not stage:
        stage = "full" if bool(flags.get("USE_OLLAMA_INTENT", False)) else "off"
    if stage not in {"off", "shadow", "percent", "full"}:
        stage = "off"
    rollout_percent = max(0, min(100, int(cfg.get("rollout_percent", 0) or 0)))
    shadow_percent = max(0, min(100, int(cfg.get("shadow_percent", 100) or 100)))
    seed = str(trace_id or uid or "default")
    bucket = stable_rollout_bucket(seed)
    invoke = False
    shadow_capture = False
    if stage == "full":
        invoke = True
        shadow_capture = True
    elif stage == "percent":
        invoke = bucket < rollout_percent
        shadow_capture = True
    elif stage == "shadow":
        invoke = False
        shadow_capture = bucket < shadow_percent
    return {
        "stage": stage,
        "rollout_percent": rollout_percent,
        "shadow_percent": shadow_percent,
        "bucket": bucket,
        "invoke_ollama": invoke,
        "shadow_capture": shadow_capture,
    }


def rule_intent_summary(query: str | None, nlp: Dict[str, Any] | None) -> str:
    q = str(query or "").strip()
    n = nlp if isinstance(nlp, dict) else {}
    intent = str(n.get("intent") or "browse").strip().lower()
    prefs = n.get("preferences") if isinstance(n.get("preferences"), dict) else {}
    use_case = str(prefs.get("use_case") or "").strip()
    attrs: List[str] = []
    if prefs.get("budget_max") is not None or prefs.get("budget_min") is not None:
        attrs.append("budget")
    if use_case:
        attrs.append(f"use_case={use_case}")
    if prefs.get("brands"):
        attrs.append("brand")
    if prefs.get("specs"):
        attrs.append("specs")
    short_q = q[:180]
    if attrs:
        return f"Intent={intent}; focus={', '.join(attrs[:3])}; query={short_q}"
    return f"Intent={intent}; query={short_q}"


def summaries_differ(a: str | None, b: str | None) -> bool:
    aa = str(a or "").strip().lower()
    bb = str(b or "").strip().lower()
    if not aa and not bb:
        return False
    return aa != bb


# ─── Main orchestrator ───────────────────────────────────────────────────────


@dataclass
class IntentRoutingResult:
    """Output of the intent routing step."""
    ollama_meta: Dict[str, Any] = field(default_factory=dict)
    model_tier: str = "small"
    llm_model: Optional[str] = None
    complexity_signals: Dict[str, Any] = field(default_factory=dict)
    timing_ms: Optional[int] = None


def resolve_intent_routing(
    *,
    query_effective: str,
    nlp: Dict[str, Any],
    complexity_context: Dict[str, Any],
    flags: Dict[str, Any],
    uid: str,
    trace_id: str,
    fast_path_enabled: bool,
    log_trace_event: Callable[..., None],
) -> IntentRoutingResult:
    """Resolve intent routing via Ollama or rule-based fallback.

    Returns the ollama_meta dict plus derived model tiering signals.
    Never raises — returns rule-based fallback on any failure.
    """
    ollama_rollout = resolve_ollama_intent_rollout(flags, uid=uid, trace_id=trace_id)
    if fast_path_enabled:
        ollama_rollout = {
            **ollama_rollout,
            "invoke_ollama": False,
            "shadow_capture": False,
            "stage": "fast_path",
        }

    ollama_meta = _run_intent_routing(
        query_effective=query_effective,
        nlp=nlp,
        complexity_context=complexity_context,
        ollama_rollout=ollama_rollout,
        trace_id=trace_id,
        log_trace_event=log_trace_event,
    )

    model_tier = "big" if bool(ollama_meta.get("complex")) else "small"
    llm_model = ollama_meta.get("selected") or ollama_meta.get("model")
    complexity_signals = (
        (ollama_meta.get("decision") or {}).get("triggers")
        or ollama_meta.get("reason")
        or {}
    )

    return IntentRoutingResult(
        ollama_meta=ollama_meta,
        model_tier=model_tier,
        llm_model=llm_model,
        complexity_signals=complexity_signals,
        timing_ms=int(ollama_meta.get("latency_ms") or 0) if ollama_meta.get("latency_ms") else None,
    )


def _run_intent_routing(
    *,
    query_effective: str,
    nlp: Dict[str, Any],
    complexity_context: Dict[str, Any],
    ollama_rollout: Dict[str, Any],
    trace_id: str,
    log_trace_event: Callable[..., None],
) -> Dict[str, Any]:
    """Inner implementation — try Ollama, fall back to rules."""
    try:
        model = select_ollama_model(query_effective, context=complexity_context)
        complex_bool = is_complex_query(query_effective, context=complexity_context)
        reason = complexity_explain(query_effective, context=complexity_context)
        path = [os.getenv("OLLAMA_SMALL_MODEL", "llama3:8b")] + (
            [os.getenv("OLLAMA_BIG_MODEL", "mixtral:8x7b")] if complex_bool else []
        )
        action = "escalate_to_big" if complex_bool else "prefer_small"
        rule_summary = rule_intent_summary(query_effective, nlp)
        ollama_summary = None
        dt_ms = None

        if ollama_rollout.get("invoke_ollama") or ollama_rollout.get("shadow_capture"):
            _intent_payload: Dict[str, Any] = {
                "model": model,
                "prompt": (
                    "Summarize the user's shopping intent in one sentence and list the top 2 attributes to consider.\n"
                    f"User Query: {query_effective}"
                ),
                "stream": False,
                "options": {"temperature": 0.2, "num_predict": 256},
            }
            if "qwen3" in model.lower():
                _intent_payload["think"] = False
            try:
                t0 = time.perf_counter()
                with httpx.Client(timeout=30.0) as client:
                    r = client.post(
                        f"{OLLAMA_URL.rstrip('/')}/api/generate", json=_intent_payload
                    )
                    r.raise_for_status()
                    resp = r.json()
                    ollama_summary = resp.get("response")
                    dt_ms = (time.perf_counter() - t0) * 1000.0
            except Exception:
                ollama_summary = None
                dt_ms = None

        selected_summary = ollama_summary if ollama_rollout.get("invoke_ollama") else rule_summary
        selected_model = model if ollama_rollout.get("invoke_ollama") else f"rule-based ({action})"
        selected_provider = "ollama" if ollama_rollout.get("invoke_ollama") else "rules"

        if ollama_rollout.get("shadow_capture"):
            try:
                log_trace_event(
                    trace_id=trace_id,
                    event_type="ollama_intent_shadow_diff",
                    source_type="agent",
                    source_id="Model_Selector",
                    target_type="system",
                    target_id=None,
                    payload={
                        "stage": ollama_rollout.get("stage"),
                        "bucket": ollama_rollout.get("bucket"),
                        "invoke_ollama": bool(ollama_rollout.get("invoke_ollama")),
                        "rule_summary": rule_summary,
                        "ollama_summary": ollama_summary,
                        "summaries_differ": summaries_differ(rule_summary, ollama_summary),
                        "latency_ms": dt_ms,
                    },
                )
            except Exception:
                pass

        return {
            "provider": selected_provider,
            "model": model if ollama_summary else None,
            "selected": selected_model,
            "complex": complex_bool,
            "intent_summary": selected_summary,
            "rule_summary": rule_summary,
            "ollama_summary": ollama_summary,
            "reason": reason,
            "path": path,
            "latency_ms": dt_ms,
            "rollout": ollama_rollout,
            "decision": {
                "action": action,
                "from": os.getenv("OLLAMA_SMALL_MODEL", "llama3:8b"),
                "to": (
                    os.getenv("OLLAMA_BIG_MODEL", "mixtral:8x7b")
                    if complex_bool
                    else os.getenv("OLLAMA_SMALL_MODEL", "llama3:8b")
                ),
                "triggers": {
                    "length_trigger": bool(reason.get("length_trigger")),
                    "matched_keywords": reason.get("matched_keywords", []),
                    "conjunction_count": reason.get("conjunction_count", 0),
                    "score": reason.get("score", 0),
                },
            },
        }
    except Exception:
        return _build_fallback_meta(query_effective, complexity_context, ollama_rollout)


def _build_fallback_meta(
    query_effective: str,
    complexity_context: Dict[str, Any],
    ollama_rollout: Dict[str, Any],
) -> Dict[str, Any]:
    """Rule-based fallback when the primary routing fails."""
    r = complexity_explain(query_effective, context=complexity_context)
    cb = is_complex_query(query_effective, context=complexity_context)
    action = "escalate_to_big" if cb else "prefer_small"
    return {
        "provider": "rules",
        "model": None,
        "selected": f"rule-based ({action})",
        "complex": cb,
        "intent_summary": rule_intent_summary(query_effective, {}),
        "reason": r,
        "path": [os.getenv("OLLAMA_SMALL_MODEL", "llama3:8b")] + (
            [os.getenv("OLLAMA_BIG_MODEL", "mixtral:8x7b")] if cb else []
        ),
        "latency_ms": None,
        "rollout": ollama_rollout,
        "decision": {
            "action": action,
            "from": os.getenv("OLLAMA_SMALL_MODEL", "llama3:8b"),
            "to": (
                os.getenv("OLLAMA_BIG_MODEL", "mixtral:8x7b")
                if cb
                else os.getenv("OLLAMA_SMALL_MODEL", "llama3:8b")
            ),
            "triggers": {
                "length_trigger": bool(r.get("length_trigger")),
                "matched_keywords": r.get("matched_keywords", []),
                "conjunction_count": r.get("conjunction_count", 0),
                "score": r.get("score", 0),
            },
        },
    }


def run_inventory_fastpath(
    *,
    query: Optional[str],
    uid: Optional[str],
    trace_id: Optional[str],
    route_t0: float,
    off_domain_fn: Callable[[Optional[str]], bool],
    unsupported_fn: Callable[[Optional[str]], bool],
    with_trace: Callable[[Dict[str, Any], Optional[str]], Dict[str, Any]],
    handle_fn: Optional[Callable[..., Optional[Dict[str, Any]]]] = None,
    record_failure: Optional[Callable[..., Any]] = None,
) -> Optional[Dict[str, Any]]:
    """Inventory stock-level fast-path — intercept stock queries BEFORE the full LLM pipeline. Stock
    counts come from the DB only (the LLM never generates them); injection attempts return a safe
    refusal. Returns the traced /suggest response to return early, or None to fall through to the full
    pipeline (off-domain / unsupported-intent queries always fall through). Never raises.

    Extracted verbatim from suggest() — the module-level helpers + handler are injected so the stage is
    testable in isolation and there is no circular import back into the router.
    """
    try:
        handle = handle_fn
        if handle is None:
            from src.app.services.inventory_query_service import handle_inventory_intent as handle
        if off_domain_fn(query) or unsupported_fn(query):
            return None
        inv = handle(query=query, uid=uid)
        if inv is None:
            return None
        return with_trace(
            {
                "recommendations": [],
                "nqe": None,
                "answer": inv.get("answer"),
                "inventory": {
                    "sku": inv.get("sku"),
                    "name": inv.get("name"),
                    "stock_level": inv.get("stock_level"),
                    "rule_id": inv.get("rule_id"),
                },
                "source": inv.get("source"),
                "injection_blocked": bool(inv.get("injection_blocked")),
                "timing": {"route_ms": int((time.perf_counter() - route_t0) * 1000)},
            },
            trace_id,
        )
    except Exception as exc:  # observability boundary: never raises
        if record_failure is not None:
            record_failure("inventory_fast_path", exc, trace_id=trace_id)
        return None
