"""Narration input stage for the recommendation route.

The LLM narrator should describe evidence the system already has, not infer the
shopper intent again from raw text. This module converts QueryUnderstanding into
a small, traceable narration envelope used by both LLM and deterministic copy.
It is vertical-agnostic: it carries values, provenance, and assumptions only.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from src.app.services.query_understanding import QueryUnderstanding, build_query_understanding


@dataclass
class NarrationPrep:
    """Grouped output of the narration prep stage — replaces the 6 loose locals the inline block
    leaked into the route (constraints, results, narration_inputs, brand_budget_answer)."""
    constraints: Dict[str, Any]
    results: Any
    narration_inputs: Any
    brand_budget_answer: Any


def prepare_narration(
    *,
    query: Any,
    query_effective: Any,
    constraints: Dict[str, Any],
    results: Any,
    filter_meta_price: Any,
    strict_image_brand_hint: Any,
    inferred_image_brand: Any,
    demote_off_category: Callable[[Any, Any], Any],
    build_brand_budget_answer: Callable[..., Any],
    query_plan: Any = None,
    answer_evidence_fn: Optional[Callable[..., Dict[str, Any]]] = None,
) -> NarrationPrep:
    """Pre-narration setup: stamp price/brand metadata onto constraints, build the narration
    envelope (build_narration_inputs + apply_narration_inputs_to_constraints — note this REBINDS
    constraints to a new dict), demote off-category results, and compute the brand/budget answer.
    Returns a NarrationPrep so the route rebinds these together instead of juggling 6 loose locals.
    The two route-local helpers are injected; never raises beyond the helpers' own contracts."""
    constraints["_price_filter_meta"] = filter_meta_price or {}
    constraints["_strict_image_brand_hint"] = strict_image_brand_hint
    constraints["_inferred_image_brand"] = inferred_image_brand
    narration_inputs = build_narration_inputs(
        query_effective or query,
        constraints,
        query_understanding=build_query_understanding(
            query_effective or query or "",
            constraints,
            query_plan=query_plan,
        ),
    )
    constraints = apply_narration_inputs_to_constraints(constraints, narration_inputs)
    # Off-category relevance guard: a primary-product query must not be led by a peripheral.
    results = demote_off_category(results, query)
    brand_budget_answer = build_brand_budget_answer(query, results, constraints)
    # Per-pick metric evidence: attach `evidence` to each result (FE-facing) + a compact prompt block so
    # the narrator grounds on price_fit/office_fit/fleet_fit/... instead of inventing suitability. The
    # builder is injected (recommend_evidence) so this stays unit-testable; never raises.
    if answer_evidence_fn is not None:
        try:
            import dataclasses as _dc
            ans_ev = answer_evidence_fn(results, constraints) or {}
            for pick in (ans_ev.get("picks") or []):
                sku = str(pick.get("sku") or "")
                for r in (results or []):
                    if isinstance(r, dict) and str(r.get("sku") or "") == sku:
                        r["evidence"] = pick.get("evidence")
                        break
            constraints["_answer_evidence"] = {k: ans_ev.get(k) for k in ("office_grade_count", "work_suitable", "use_case")}
            from src.app.services.recommend_evidence import render_evidence_block as _reb
            narration_inputs = _dc.replace(narration_inputs, pick_evidence_block=_reb(ans_ev))
        except Exception:
            pass
    return NarrationPrep(
        constraints=constraints,
        results=results,
        narration_inputs=narration_inputs,
        brand_budget_answer=brand_budget_answer,
    )


def run_narration(
    timing_breakdown: Dict[str, Any],
    *,
    mode: str,
    query: Any,
    results: Any,
    constraints: Any,
    summ_model: Any,
    trace_id: Any,
    combined_preamble: Any,
    narration_inputs: Any,
    summarize_fn: Callable[..., Tuple[Any, Any]],
    executor: Any = None,
    redis: Any = None,
    submit_fn: Optional[Callable[..., Any]] = None,
    guard_evidence: Any = None,
    final_products: Any = None,
) -> Tuple[Optional[str], Optional[str]]:
    """Tier-1 narration latency control. Returns (assistant_message, llm_summary_job_id) and writes
    narration_mode / summary_ms / narration_pending into ``timing_breakdown``.

    LLM narration was measured at 85-91% of route latency, so the mode is the latency lever:
      * ``blocking`` (default): call the LLM now (timed via StageTimer) -> prose.
      * ``skip``: no LLM call -> (None, None); the route's deterministic fallback fills the message.
      * ``async``: skip now + enqueue the prose as a background job (client polls /narration/{id}).
    ``summarize_fn`` is injected (the route's _summarize_results) so this is unit-testable without an
    LLM. Never raises on the async-enqueue path (job id -> None on failure)."""
    from src.app.observability.stage_timer import StageTimer

    m = str(mode or "blocking").strip().lower()
    if m not in ("blocking", "skip", "async"):
        m = "blocking"
    if isinstance(timing_breakdown, dict):
        timing_breakdown["narration_mode"] = m

    assistant_message: Optional[str] = None
    llm_summary_job_id: Optional[str] = None

    if m == "blocking":
        # Latency bound. Cap the LLM wait; on timeout fall back to the deterministic grounded
        # message (now guard-truthful) instead of blocking the whole response. This bounds p95
        # WITHOUT flipping the narration mode (LLM prose still returned when it's fast enough).
        # Budget resolution (B3): env RECOMMEND_NARRATION_TIMEOUT_SEC -> model descriptor
        # (config/model_profiles.json) -> 8s. The old hardcoded 8s was mute-layer 3 (bb4cd0a):
        # smaller than EVERY model's think latency, so prose was always silently discarded.
        try:
            from src.app.services.model_profiles import narration_timeout_s as _mp_narr_timeout
            _budget = _mp_narr_timeout(summ_model)
        except Exception:
            _budget = 8.0
        with StageTimer(timing_breakdown, "summary_ms"):  # time the dominant LLM cost
            if _budget > 0 and executor is not None:
                import concurrent.futures as _cf
                _fut = executor.submit(
                    summarize_fn, query, results, constraints, summ_model, trace_id,
                    context_preamble=combined_preamble, narration_inputs=narration_inputs,
                )
                try:
                    assistant_message, llm_summary_job_id = _fut.result(timeout=_budget)
                except _cf.TimeoutError:
                    if isinstance(timing_breakdown, dict):
                        timing_breakdown["narration_timed_out"] = True
                    assistant_message, llm_summary_job_id = None, None  # deterministic fallback fills it
            else:
                assistant_message, llm_summary_job_id = summarize_fn(
                    query, results, constraints, summ_model, trace_id,
                    context_preamble=combined_preamble,
                    narration_inputs=narration_inputs,
                )
        return assistant_message, llm_summary_job_id

    # skip / async: no blocking LLM call — the deterministic grounded message fills in downstream.
    if isinstance(timing_breakdown, dict):
        timing_breakdown["summary_ms"] = 0
        timing_breakdown["narration_pending"] = (m == "async")
    if m == "async":
        if submit_fn is None:
            try:
                from src.app.services.recommend_narration_jobs import submit_narration as submit_fn  # type: ignore
            except Exception:
                submit_fn = None
        if submit_fn is not None:
            # B4: the async job must pass the SAME claim guard as the blocking path — otherwise
            # ungrounded prose (invented SKUs/prices, the phi4 A/B failure class) reaches the buyer
            # through the out-of-band swap-in with no verification. On rejection the job yields no
            # message, so the frontend simply keeps the deterministic grounded answer it already
            # rendered — the swap only ever upgrades truthful prose.
            import copy as _copy
            # PX0 (GPT-5.5 #1/#4): narrate over — and guard + [N]-dereference against — the FINAL
            # buyer-visible products, not the pre-cleanup `results` (which still held dropped
            # pharmacy/accessory items at snapshot time). Deep-copy: the request thread keeps
            # annotating these dicts (stock_level etc.) after submit (audit #15).
            _src = final_products if final_products is not None else results
            try:
                _final_snapshot = _copy.deepcopy(list(_src or []))
            except Exception:
                _final_snapshot = list(_src or [])
            _constraints_snapshot = dict(constraints or {})
            _guard_evidence = guard_evidence

            def _guarded_summarize(*a: Any, **k: Any) -> Any:
                out = summarize_fn(*a, **k)
                msg = out[0] if isinstance(out, tuple) else out
                if isinstance(msg, str) and msg.strip() and _final_snapshot:
                    try:
                        from src.app.services.product_claim_guard import guard_enabled, verify_product_narration
                        if guard_enabled():
                            gr = verify_product_narration(
                                msg, _final_snapshot,
                                budget_min=_constraints_snapshot.get("budget_min"),
                                budget_max=_constraints_snapshot.get("budget_max"),
                                preamble=_guard_evidence,
                            )
                            if not getattr(gr, "grounded", True):
                                _viol = list(getattr(gr, "violations", []))[:6]
                                try:
                                    from src.app.services.decision_log import log_trace_event
                                    log_trace_event(
                                        trace_id=trace_id, event_type="narration_guard_rejected",
                                        source_type="agent", source_id="Product_Claim_Guard",
                                        target_type="system", target_id=None,
                                        payload={"violations": _viol,
                                                 "used_llm": False, "fallback_reason": "ungrounded_async_narration"},
                                    )
                                except Exception:
                                    pass
                                # third element rides into the job record: a no-prose outcome
                                # must be diagnosable from the poll endpoint, never silent
                                return None, None, {"guard": "rejected", "violations": _viol}
                    except Exception:
                        # FAIL CLOSED (audit #4): a guard that crashes must never certify — the
                        # deterministic answer stands and the record says verification errored.
                        return None, None, {"guard": "error"}
                # #4: dereference [N] labels the way the sync finalizer does, so raw '[1]' never
                # reaches the buyer through the async swap.
                if isinstance(msg, str) and "[" in msg and _final_snapshot:
                    try:
                        from src.app.services.recommend_response_finalizer import _dereference_product_labels
                        _clean = _dereference_product_labels({"assistant_message": msg, "results": _final_snapshot})
                        _dm = _clean.get("assistant_message")
                        if isinstance(_dm, str) and _dm.strip():
                            return (_dm,) + tuple(out[1:]) if isinstance(out, tuple) else _dm
                    except Exception:
                        pass
                return out

            try:
                llm_summary_job_id = submit_fn(
                    executor, redis, _guarded_summarize,
                    query, _final_snapshot, _constraints_snapshot, summ_model, trace_id,
                    context_preamble=combined_preamble, narration_inputs=narration_inputs,
                )
            except Exception:
                llm_summary_job_id = None
    return assistant_message, llm_summary_job_id


def build_narration_preamble(
    *,
    kv: Any,
    structured_state: Any,
    constraints: Dict[str, Any],
    prior_shortlist: Any,
    db: Any,
    trace_id: Any,
    mem: Any,
    uid: Any,
    session_context_summary: Any,
    image_cv_signals_parsed: Any,
    llm_model: Any,
    image_feature_allowlist: Any,
    build_context_preamble: Callable[..., Any],
    trace_to_context_summary: Callable[..., Any],
    image_security_preamble_note: Callable[..., Any],
    query: Optional[str] = None,
) -> Tuple[Optional[str], Any]:
    """Assemble the LLM narration preamble and resolve the summary model.

    Order: conversation memory (build_context_preamble) -> decision-trace context -> recent session
    excerpt -> SANITIZED image notes (QR status + off-topic). Untrusted image-derived text (decoded
    QR/OCR) never enters the preamble — only a quarantine status — preserving the "an image cannot
    issue instructions" boundary. Also threads the image-trust verdict into ``constraints`` in place
    so the summarizer can fence blocked signals. Returns (combined_preamble, summ_model). The three
    route-local helpers are injected so this is unit-testable; never raises."""
    import json as _json
    import os as _os

    ctx_preamble: Optional[str] = None
    trace_ctx: Optional[str] = None
    try:
        prior_prods: Optional[list] = None
        try:
            if prior_shortlist and db is not None:
                from sqlalchemy import text as _sqla_text
                skus = [str(s) for s in prior_shortlist[:4] if s]
                if skus:
                    bind = {f"s{i}": sk for i, sk in enumerate(skus)}
                    placeholders = ", ".join(f":s{i}" for i in range(len(skus)))
                    rows = db.execute(
                        _sqla_text(f"SELECT sku, name, price_cents, specs FROM products WHERE sku IN ({placeholders}) AND active=1"),
                        bind,
                    ).mappings().all()
                    prior_prods = [
                        {"sku": r["sku"], "name": r["name"], "price_cents": r["price_cents"],
                         "specs": _json.loads(r["specs"]) if isinstance(r["specs"], str) else (r["specs"] or {})}
                        for r in rows
                    ]
        except Exception:
            prior_prods = None
        ctx_preamble = build_context_preamble(
            kv=kv if isinstance(kv, dict) else {},
            structured_state=structured_state if isinstance(structured_state, dict) else {},
            constraints=constraints,
            prior_shortlist_products=prior_prods,
        ) or None
    except Exception:
        pass
    try:
        trace_ctx = trace_to_context_summary(trace_id, mem, uid) or None
    except Exception:
        pass

    session_excerpt = (str(session_context_summary or "").strip())[:400] or None
    parts = [p for p in (ctx_preamble, trace_ctx, session_excerpt) if p]
    combined: Optional[str] = "\n\n".join(parts) if parts else None
    # EVIDENCE PROVENANCE (audit 2026-07-08): the guard may only treat PLATFORM-AUTHORED text as
    # legitimate evidence. session_excerpt and trace_ctx carry conversation-derived content — a
    # URL the buyer typed, or their "120 fps" wish — and treating them as evidence let parroted
    # quarantined URLs bypass the guard and user text disable the benchmark rule. ctx_preamble is
    # platform-assembled (structured slots + prior CATALOG products) and stays in scope.
    _guard_parts: list = [p for p in (ctx_preamble,) if p]

    # QR signal -> SANITIZED status only (never the decoded payload).
    try:
        qr_note = image_security_preamble_note(image_cv_signals_parsed)
        if qr_note:
            combined = (combined + "\n\n" + qr_note) if combined else qr_note
            _guard_parts.append(qr_note)
    except Exception:
        pass
    # Off-topic image note (vertical-blind fallback text).
    try:
        if isinstance(image_cv_signals_parsed, dict) and image_cv_signals_parsed.get("image_relevance") == "off_topic":
            off_note = str(
                image_cv_signals_parsed.get("image_relevance_note")
                or "The uploaded image does not appear to match this store's products. "
                   "Recommendations will be based on the text query only."
            )
            combined = (combined + "\n\n" + off_note) if combined else off_note
            _guard_parts.append(off_note)
    except Exception:
        pass

    # Capability registry (B1): the store's declared boundary (no payment plans, autonomy
    # ceiling, backorder consent) as authoritative facts, only when the query makes them
    # relevant. Without this the narrator fabricates offerings (A/B rounds 3-4: all models).
    try:
        if query:
            from src.app.services.capability_registry import capability_preamble_note
            cap_note = capability_preamble_note(query)
            if cap_note:
                combined = (combined + "\n\n" + cap_note) if combined else cap_note
                _guard_parts.append(cap_note)
    except Exception:
        pass

    # C2 knowledge pool (Lane-3 curated domain evidence): citable facts the narrator may state
    # (spec tiers, workload floors) — platform-authored, so guard-legitimate by construction.
    try:
        if query:
            from src.app.services.knowledge_pool import knowledge_note
            kn = knowledge_note(query, use_case=str((constraints or {}).get("use_case") or "") or None)
            if kn:
                combined = (combined + "\n\n" + kn) if combined else kn
                _guard_parts.append(kn)
    except Exception:
        pass

    # Publish the provenance-scoped guard evidence for BOTH guard paths (blocking + async job).
    if isinstance(constraints, dict):
        constraints["_guard_evidence"] = "\n\n".join(_guard_parts) if _guard_parts else None

    # Resolve a real model for the summary (llm_model may be a display name like
    # "rule-based (prefer_small)" when the intent rollout is off).
    summ_model = llm_model
    if not summ_model or "rule-based" in str(summ_model) or " " in str(summ_model):
        summ_model = _os.getenv("OLLAMA_SUMMARY_MODEL", _os.getenv("OLLAMA_MEDIUM_MODEL", "qwen3:14b"))

    # Thread the image-trust verdict into constraints (in place) for the security fence.
    try:
        verdict = getattr(image_feature_allowlist, "verdict", "full")
        if verdict != "full" and isinstance(constraints, dict):
            constraints["_image_feature_allowlist_verdict"] = verdict
            constraints["_image_feature_blocked_signals"] = getattr(image_feature_allowlist, "blocked_signals", [])
    except Exception:
        pass

    return combined, summ_model


def apply_product_claim_guard(
    assistant_message: Optional[str],
    *,
    query: Any,
    results: Any,
    constraints: Any,
    brand_budget_answer: Any,
    trace_id: Any,
    deterministic_fn: Callable[..., str],
    guard_enabled_fn: Optional[Callable[[], bool]] = None,
    verify_fn: Optional[Callable[..., Any]] = None,
    log_fn: Optional[Callable[..., Any]] = None,
    combined_preamble: Optional[str] = None,
) -> Optional[str]:
    """Grounded narration guard (flag COMMERCE_NARRATION_GUARD). The LLM is a narrator over evidence,
    not a source of truth: if it invents a product/price/spec or parrots a quarantined payload, reject
    the prose and fall back to deterministic grounded copy (and trace the rejection). Returns the
    (possibly replaced) assistant_message. Flag-off / no message / no results -> unchanged. The
    deterministic copy generator is injected; never raises.

    ``combined_preamble`` widens the guard's evidence scope to the platform-authored narration
    context (step-up facts, capability registry, market evidence) so honest citations of the
    platform's OWN facts are not rejected — the mute-layer-7 scope fix (bb4cd0a)."""
    _status = "disabled"
    try:
        if guard_enabled_fn is None or verify_fn is None:
            from src.app.services.product_claim_guard import guard_enabled as _ge, verify_product_narration as _vp
            guard_enabled_fn = guard_enabled_fn or _ge
            verify_fn = verify_fn or _vp
        if guard_enabled_fn() and not (assistant_message and results):
            _status = "skipped"
        if guard_enabled_fn() and assistant_message and results:
            # Honest telemetry (audit #13): status flips to "passed" only AFTER verification
            # returns; a verify crash lands in the outer except and reports guard_error — never
            # a false "passed". No TypeError retry: it double-ran side-effecting verifiers and
            # masked real TypeErrors as signature mismatches.
            try:
                gr = verify_fn(
                    assistant_message, results,
                    budget_min=(constraints or {}).get("budget_min"),
                    budget_max=(constraints or {}).get("budget_max"),
                    preamble=combined_preamble,
                )
                _status = "passed"
            except Exception:
                # FAIL CLOSED: a guard that cannot verify must not certify — deterministic copy ships.
                gr = None
                _status = "guard_error_fell_back"
            if gr is None or not getattr(gr, "grounded", True):
                if gr is not None:
                    _status = "fell_back_to_deterministic"
                assistant_message = deterministic_fn(
                    query, results, constraints, brand_budget_answer=brand_budget_answer
                )
                try:
                    if log_fn is None:
                        from src.app.services.decision_log import log_trace_event as log_fn  # type: ignore
                    log_fn(
                        trace_id=trace_id, event_type="narration_guard_rejected",
                        source_type="agent", source_id="Product_Claim_Guard",
                        target_type="system", target_id=None,
                        payload={"violations": list(getattr(gr, "violations", []))[:6] if gr is not None else ["guard_error"],
                                 "used_llm": False, "fallback_reason": "ungrounded_product_claim"},
                    )
                except Exception:
                    pass
    except Exception:
        pass
    # Honest reporting: record the true guard state so telemetry never shows a false "passed".
    if isinstance(constraints, dict):
        constraints["_claim_guard_status"] = _status
    return assistant_message


@dataclass(frozen=True)
class NarrationInputs:
    query_text: str
    budget_min: Optional[float] = None
    budget_max: Optional[float] = None
    budget_text: str = ""
    use_case: str = ""
    buyer_persona: str = ""
    brands: List[str] = field(default_factory=list)
    missing: List[str] = field(default_factory=list)
    assumptions: List[Dict[str, Any]] = field(default_factory=list)
    provenance: Dict[str, str] = field(default_factory=dict)
    pick_evidence_block: str = ""  # compact per-pick metric evidence the narrator must ground on

    def to_dict(self) -> Dict[str, Any]:
        return {
            "query_text": self.query_text,
            "budget_min": self.budget_min,
            "budget_max": self.budget_max,
            "budget_text": self.budget_text,
            "use_case": self.use_case,
            "buyer_persona": self.buyer_persona,
            "brands": list(self.brands),
            "missing": list(self.missing),
            "assumptions": list(self.assumptions),
            "provenance": dict(self.provenance),
            "pick_evidence_block": self.pick_evidence_block,
        }


def _num(value: Any) -> Optional[float]:
    if isinstance(value, (int, float)):
        return float(value)
    try:
        text = str(value or "").replace(",", "").replace("$", "").strip()
        return float(text) if text else None
    except Exception:
        return None


def _budget_text(budget_min: Optional[float], budget_max: Optional[float]) -> str:
    if budget_min is not None and budget_max is not None:
        return f"${int(budget_min):,}-${int(budget_max):,}"
    if budget_max is not None:
        return f"under ${int(budget_max):,}"
    if budget_min is not None:
        return f"above ${int(budget_min):,}"
    return ""


def build_narration_inputs(
    query: str | None,
    constraints: Dict[str, Any] | None,
    *,
    query_understanding: QueryUnderstanding | None = None,
) -> NarrationInputs:
    c = dict(constraints or {})
    qu = query_understanding or build_query_understanding(str(query or ""), c)

    budget_min = qu.budget_min if qu.budget_min is not None else _num(c.get("budget_min"))
    budget_max = qu.budget_max if qu.budget_max is not None else _num(c.get("budget_max"))
    use_case = str(qu.use_case or c.get("use_case") or "").strip()
    brands = list(qu.brands or [])
    if not brands:
        raw_brands = c.get("brands") or c.get("brand_hints") or []
        brands = [str(b).strip().lower() for b in raw_brands if str(b).strip()] if isinstance(raw_brands, list) else []
    shopper_intent = c.get("shopper_intent") if isinstance(c.get("shopper_intent"), dict) else {}
    buyer_persona = str(
        c.get("buyer_persona")
        or c.get("inferred_persona")
        or shopper_intent.get("persona")
        or ""
    ).strip()

    return NarrationInputs(
        query_text=str(query or qu.query_text or ""),
        budget_min=budget_min,
        budget_max=budget_max,
        budget_text=_budget_text(budget_min, budget_max),
        use_case=use_case,
        buyer_persona=buyer_persona,
        brands=brands,
        missing=list(qu.missing or []),
        assumptions=list(qu.assumptions or []),
        provenance=dict(qu.provenance or {}),
    )


def apply_narration_inputs_to_constraints(
    constraints: Dict[str, Any] | None,
    narration: NarrationInputs,
) -> Dict[str, Any]:
    """Return a copy of constraints with QueryUnderstanding-backed narration fields filled."""
    out = dict(constraints or {})
    if narration.budget_min is not None and out.get("budget_min") is None:
        out["budget_min"] = narration.budget_min
    if narration.budget_max is not None and out.get("budget_max") is None:
        out["budget_max"] = narration.budget_max
    if narration.use_case and not out.get("use_case"):
        out["use_case"] = narration.use_case
    if narration.brands and not out.get("brands"):
        out["brands"] = list(narration.brands)
    out["_query_understanding"] = narration.to_dict()
    return out


def build_narration_evidence_block(narration: NarrationInputs) -> str:
    """Compact prompt block: what the narrator may rely on, with provenance."""
    lines: list[str] = ["Structured interpretation evidence:"]
    if narration.budget_text:
        src = narration.provenance.get("budget_max") or narration.provenance.get("budget_min") or "unknown"
        lines.append(f"- Budget: {narration.budget_text} (source: {src})")
    if narration.use_case:
        src = narration.provenance.get("use_case") or "unknown"
        lines.append(f"- Use case: {narration.use_case.replace('_', ' ')} (source: {src})")
    if narration.brands:
        src = narration.provenance.get("brands") or "unknown"
        lines.append(f"- Brand preference: {', '.join(narration.brands[:4])} (source: {src})")
    if narration.assumptions:
        rendered = []
        for item in narration.assumptions[:4]:
            if isinstance(item, dict) and item.get("field"):
                rendered.append(f"{item.get('field')}={item.get('value')} ({item.get('basis')})")
        if rendered:
            lines.append("- Overridable assumptions: " + "; ".join(rendered))
    block = str(getattr(narration, "pick_evidence_block", "") or "").strip()
    if block:
        lines.append(block)  # per-pick metric evidence (price_fit/office_fit/fleet_fit/...) for grounded narration
    if len(lines) == 1:
        return ""
    return "\n".join(lines)
