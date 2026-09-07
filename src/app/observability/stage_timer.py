"""StageTimer (0.5) — honest per-stage latency instrumentation.

A tiny, pure, reusable context manager that records elapsed milliseconds for a
named pipeline stage into a shared `timing_breakdown` dict, plus an accounting
helper that surfaces how much of the total route time is UNEXPLAINED by the named
stages. Latency claims ("sub-second fast path") are only defensible when the named
stages add up to the measured total — `summarize_timing` makes the gap visible
instead of letting unaccounted time hide.

No I/O, no tracing dependency — safe to use anywhere; never raises.
"""
from __future__ import annotations

import time
from typing import Any, Dict, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from src.app.services.recommendation_core.envelope import CoreResponse


class StageTimer:
    """Context manager: `with StageTimer(tb, "summary_ms"): ...` records elapsed ms.

    On exit it writes int(elapsed_ms) under `key` into `timing_breakdown`. Swallows
    nothing from the wrapped block (exceptions propagate) but never fails on its own
    bookkeeping.
    """

    __slots__ = ("_tb", "_key", "_t0")

    def __init__(self, timing_breakdown: dict[str, Any], key: str):
        self._tb = timing_breakdown if isinstance(timing_breakdown, dict) else {}
        self._key = key
        self._t0 = 0.0

    def __enter__(self) -> "StageTimer":
        self._t0 = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        try:
            self._tb[self._key] = int((time.perf_counter() - self._t0) * 1000)
        except Exception:
            pass
        return False  # never suppress exceptions from the wrapped block


def summarize_timing(timing_breakdown: dict[str, Any], total_key: str = "route_total_ms") -> dict[str, Any]:
    """Add `accounted_ms` (sum of *_ms stage keys) and `unaccounted_ms` (total minus
    accounted) to the breakdown so unexplained latency is visible, not hidden.

    Only numeric keys ending in `_ms` (excluding the total and the derived keys) are
    summed. Safe + idempotent; returns the same dict for chaining.
    """
    if not isinstance(timing_breakdown, dict):
        return {}
    derived = {total_key, "accounted_ms", "unaccounted_ms"}
    accounted = 0
    for k, v in list(timing_breakdown.items()):
        if k in derived or not str(k).endswith("_ms"):
            continue
        try:
            accounted += int(v)
        except (TypeError, ValueError):
            continue
    timing_breakdown["accounted_ms"] = accounted
    total = timing_breakdown.get(total_key)
    if isinstance(total, (int, float)):
        timing_breakdown["unaccounted_ms"] = max(int(total) - accounted, 0)
    return timing_breakdown


def build_timing_breakdown(
    core: CoreResponse, *, total_ms: float, router_metrics: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Project one request-scoped timing contract from typed stage results.

    ``retrieval_ms`` is diagnostic and contained within ``plan_ms``. Keeping that relationship
    explicit prevents operators from adding overlapping phases and inventing a larger total.
    """
    stages = [item.as_dict() for item in core.stage_results]
    route_ms = sum(
        float(item.get("latency_ms") or 0.0)
        for item in stages if item.get("stage") == "route+intent"
    )
    plan_ms = sum(
        float(item.get("latency_ms") or 0.0)
        for item in stages if str(item.get("stage") or "").startswith("plan:")
    )
    post_stages = [
        item for item in stages
        if item.get("stage") != "route+intent"
        and not str(item.get("stage") or "").startswith("plan:")
    ]
    post_ms = sum(float(item.get("latency_ms") or 0.0) for item in post_stages)
    fulfillment_ms = sum(
        float(item.get("latency_ms") or 0.0)
        for item in post_stages if item.get("stage") == "fulfillment_preview"
    )
    retrieval_ms = float((core.extras.get("evidence") or {}).get("latency_ms") or 0.0)
    model = dict(router_metrics or {})
    router_queue_ms = float(model.get("queue_ms") or 0.0)
    router_load_ms = float(model.get("load_ms") or 0.0)
    router_prefill_ms = float(model.get("prompt_eval_ms") or 0.0)
    router_decode_ms = float(model.get("decode_ms") or 0.0)
    router_wall_ms = float(model.get("wall_ms") or 0.0)
    router_model_execution_ms = float(model.get("model_execution_ms") or (
        router_load_ms + router_prefill_ms + router_decode_ms
    ))
    router_provider_total_ms = float(model.get("provider_total_ms") or 0.0)
    router_provider_internal_overhead_ms = float(
        model.get("provider_internal_overhead_ms") or max(
            0.0, router_provider_total_ms - router_model_execution_ms,
        )
    )
    router_transport_overhead_ms = float(
        model.get("transport_overhead_ms") or (
            max(0.0, router_wall_ms - router_queue_ms - router_provider_total_ms)
            if router_provider_total_ms else 0.0
        )
    )
    router_provider_overhead_ms = max(
        0.0,
        router_wall_ms
        - router_queue_ms
        - router_load_ms
        - router_prefill_ms
        - router_decode_ms,
    )
    return {
        "recommendation_total_ms": round(float(total_ms), 1),
        "route_total_ms": round(route_ms, 1),
        "plan_ms": round(plan_ms, 1),
        "retrieval_ms": round(retrieval_ms, 1),
        "post_stage_ms": round(post_ms, 1),
        "fulfillment_preview_ms": round(fulfillment_ms, 1),
        "router_queue_ms": round(router_queue_ms, 1),
        "router_load_ms": round(router_load_ms, 1),
        "router_prefill_ms": round(router_prefill_ms, 1),
        "router_decode_ms": round(router_decode_ms, 1),
        "router_model_execution_ms": round(router_model_execution_ms, 1),
        "router_provider_total_ms": round(router_provider_total_ms, 1),
        "router_provider_internal_overhead_ms": round(router_provider_internal_overhead_ms, 1),
        "router_transport_overhead_ms": round(router_transport_overhead_ms, 1),
        "router_provider_overhead_ms": round(router_provider_overhead_ms, 1),
        "router_wall_ms": round(router_wall_ms, 1),
        "router_outcome": str(model.get("outcome") or "not_called"),
        "router_model": str(model.get("model") or "not_called"),
        "retrieval_contained_in_plan": True,
        "stages": stages,
    }
