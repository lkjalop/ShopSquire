"""
═══════════════════════════════════════════════════════════════════════════
recommend_post_pipeline — CORE (vertical-agnostic)
═══════════════════════════════════════════════════════════════════════════
Post-processing pipeline for the recommend route's final response.

Applies: policy gates → redaction → model watermark → model theft protection
→ probe detection → billing meter → security analysis → incident review
→ checkout handoff → compound composition → response finalization → latency.

Extracted from the tail of recommend.py suggest() to reduce the monolith body.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple


@dataclass
class PostPipelineInput:
    """All inputs needed for the post-processing pipeline."""
    payload: Dict[str, Any]
    trace_id: str
    decision_id: Optional[str]
    flags: Dict[str, Any]
    uid: str
    uid_hash: str
    query: str
    severity: str
    agent_chain: List[Dict[str, Any]]
    retrieved_context: Dict[str, Any]
    skip_recommend_observer: bool
    probe_result: Dict[str, Any]
    started_at: Optional[float] = None


@dataclass
class PostPipelineHooks:
    """Injected dependencies from the route."""
    get_policy: Callable[[str], Dict[str, Any]]
    apply_post_policy: Callable[[str, Dict[str, Any]], Tuple[Dict[str, Any], List]]
    redact_payload: Callable[[Dict[str, Any]], Tuple[Dict[str, Any], Any, Any]]
    ensure_trace_response: Callable[..., Dict[str, Any]]
    dedupe_next_questions_for_render: Callable[[List], List]
    build_model_watermark: Callable[..., str]
    build_output_fingerprint: Callable[[Dict[str, Any]], str]
    apply_model_theft_output_protection: Callable[..., Dict[str, Any]]
    record_meter_event: Callable[..., None]
    analyze_payload: Callable[[Dict[str, Any]], Dict[str, Any]]
    emit_security_event: Callable[..., None]
    auto_create_incident_for_review: Callable[..., None]
    apply_checkout_handoff: Callable[[Dict[str, Any], Any], Dict[str, Any]]
    recommend_context_cls: Any  # RecommendContext class
    compose_compound_if_needed: Callable[[Dict[str, Any], Any], Dict[str, Any]]
    finalize_response_payload: Callable[[Dict[str, Any]], Dict[str, Any]]
    log_trace_event: Callable[..., None]
    request: Any  # FastAPI Request
    tracer: Any  # OpenTelemetry tracer


def run_post_pipeline(inp: PostPipelineInput, hooks: PostPipelineHooks) -> Dict[str, Any]:
    """Apply the full post-processing pipeline and return the final response dict.

    Mutates ``inp.agent_chain`` and ``inp.retrieved_context`` in place (policy gates).
    Never raises — internal blocks are individually guarded.
    """
    trace_id = inp.trace_id
    decision_id = inp.decision_id
    flags = inp.flags

    # ── Policy ────────────────────────────────────────────────────────────────
    policy = hooks.get_policy("recommend")
    inp.payload["policy_version"] = policy.get("version", inp.payload.get("policy_version"))
    payload_policy, deltas = hooks.apply_post_policy("recommend", inp.payload)

    try:
        payload_policy = hooks.ensure_trace_response(payload_policy or {}, trace_id, flags)
    except Exception:
        pass
    try:
        if isinstance(payload_policy.get("next_questions"), list):
            payload_policy["next_questions"] = hooks.dedupe_next_questions_for_render(
                payload_policy.get("next_questions")
            )
    except Exception:
        pass
    try:
        inp.agent_chain.append({
            "agent": "Policy_Agent",
            "policy_version": payload_policy.get("policy_version"),
            "deltas": len(deltas or []),
            "duration_ms": None,
        })
        inp.retrieved_context["policy_gates"] = deltas or []
        try:
            hooks.log_trace_event(
                trace_id=decision_id or trace_id,
                event_type="policy_gate",
                source_type="agent",
                source_id="Policy_Agent",
                target_type="system",
                target_id=None,
                payload={"policy_version": payload_policy.get("policy_version"), "deltas": deltas},
            )
        except Exception:
            pass
    except Exception:
        pass

    # ── Redaction ─────────────────────────────────────────────────────────────
    redacted, changes, pci = hooks.redact_payload(payload_policy)
    try:
        redacted = hooks.ensure_trace_response(redacted or {}, decision_id or trace_id, flags)
    except Exception:
        pass
    try:
        if isinstance(redacted.get("next_questions"), list):
            redacted["next_questions"] = hooks.dedupe_next_questions_for_render(
                redacted.get("next_questions")
            )
    except Exception:
        pass

    # ── Model watermark ───────────────────────────────────────────────────────
    try:
        wm = hooks.build_model_watermark(
            trace_id=decision_id or trace_id,
            model=str(redacted.get("llm_model") or redacted.get("model_tier") or ""),
            payload_hint=str(redacted.get("assistant_message") or "")[:120],
        )
        redacted["model_watermark"] = wm
        redacted["model_output_fingerprint"] = hooks.build_output_fingerprint(redacted)
        if str(os.getenv("MODEL_THEFT_WATERMARK_APPEND_TEXT", "0")).lower() in ("1", "true", "yes"):
            if isinstance(redacted.get("assistant_message"), str) and redacted.get("assistant_message"):
                redacted["assistant_message"] = f"{redacted['assistant_message']} [{wm}]"
    except Exception:
        pass

    # ── Model theft protection ────────────────────────────────────────────────
    redacted = hooks.apply_model_theft_output_protection(
        redacted, trace_id=decision_id or trace_id
    )

    # ── Probe detection ───────────────────────────────────────────────────────
    try:
        if bool(inp.probe_result.get("detected")):
            redacted["security"] = redacted.get("security") or {}
            redacted["security"]["systematic_probing"] = {
                "detected": True,
                "reason": inp.probe_result.get("reason"),
                "score": inp.probe_result.get("score"),
            }
            redacted["status"] = redacted.get("status") or "review_required"
    except Exception:
        pass

    # ── Billing meter ─────────────────────────────────────────────────────────
    try:
        tenant_for_billing = (
            hooks.request.headers.get("X-Tenant-Id")
            or hooks.request.headers.get("x-tenant-id")
            or "default"
        )
        hooks.record_meter_event(
            tenant_id=str(tenant_for_billing),
            metric="recommend_requests",
            quantity=1.0,
            source="api",
            metadata={"trace_id": decision_id or trace_id, "uid_hash": inp.uid_hash},
        )
    except Exception:
        pass

    # ── Security output analysis ──────────────────────────────────────────────
    with hooks.tracer.start_as_current_span("recommend.security_analyze_output_final"):
        if inp.skip_recommend_observer:
            final_out = {"severity": "info", "details": {"signals": {}, "reason": "observer_skipped"}}
        else:
            final_out = hooks.analyze_payload(
                {
                    "uid": inp.uid,
                    "assistant_message": redacted.get("assistant_message"),
                    "next_questions": redacted.get("next_questions") or [],
                    "results": [
                        {"sku": r.get("sku"), "name": r.get("name"), "price": r.get("price")}
                        for r in (redacted.get("results") or [])
                        if isinstance(r, dict)
                    ][:8],
                }
            )
    try:
        if not inp.skip_recommend_observer:
            hooks.emit_security_event(
                "/api/v1/recommend/suggest:output",
                {
                    "proposal": redacted.get("proposal"),
                    "analysis": {**final_out.get("details", {}), "critique_deltas": deltas},
                },
                request=hooks.request,
            )
    except Exception:
        pass

    # ── Final incident review ─────────────────────────────────────────────────
    try:
        hooks.auto_create_incident_for_review(
            payload=redacted,
            trace_id=trace_id,
            uid=inp.uid,
            query=inp.query,
            severity=inp.severity,
            source="recommend_main",
        )
    except Exception:
        pass

    # ── Checkout handoff ──────────────────────────────────────────────────────
    redacted = hooks.apply_checkout_handoff(
        redacted,
        hooks.recommend_context_cls(query=inp.query, uid=inp.uid),
    )

    # ── Final transforms ──────────────────────────────────────────────────────
    redacted = hooks.compose_compound_if_needed(redacted, redacted.get("trace_id"))
    redacted = hooks.finalize_response_payload(redacted)
    timing = redacted.setdefault("timing_breakdown", {})
    timing.setdefault("compound_needed", False)
    timing.setdefault("compound_ms", 0)
    if inp.started_at is not None:
        timing["route_total_ms"] = int((time.perf_counter() - inp.started_at) * 1000)

    # ── Latency recording ─────────────────────────────────────────────────────
    try:
        from src.app.observability.latency_tracker import get_recommend_tracker
        _lt = get_recommend_tracker()
        _route_ms = (redacted.get("timing_breakdown") or {}).get("route_total_ms")
        _cache_hit = bool((redacted.get("timing_breakdown") or {}).get("catalog_profile_cache_hit"))
        if _route_ms is not None:
            _lt.record(float(_route_ms), cache_hit=_cache_hit)
    except Exception:
        pass

    return redacted
