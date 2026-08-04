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
from typing import Any


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
