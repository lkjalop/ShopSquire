"""Rolling latency tracker — p50/p95/p99 percentile measurement.

Lightweight, lock-free (thread-safe via append-only deque), no I/O. Stores the
last N request durations and computes on-demand percentiles for SLO dashboards
and the /admin/bi/latency endpoint.

Works whether Redis is up or not — the tracker is process-local and measures
actual observed latencies (cache-hit = fast, cache-miss + Ollama = slow).
"""
from __future__ import annotations

import time
from collections import deque
from typing import Any, Dict, Optional


_DEFAULT_WINDOW = 500  # keep last 500 measurements


class LatencyTracker:
    """Rolling window of request latencies for a named pipeline."""

    __slots__ = ("_name", "_window", "_cold", "_warm")

    def __init__(self, name: str = "recommend", window: int = _DEFAULT_WINDOW):
        self._name = name
        self._window: int = max(10, window)
        self._cold: deque[float] = deque(maxlen=self._window)
        self._warm: deque[float] = deque(maxlen=self._window)

    def record(self, duration_ms: float, *, cache_hit: bool = False) -> None:
        """Record a single request duration (milliseconds)."""
        if cache_hit:
            self._warm.append(float(duration_ms))
        else:
            self._cold.append(float(duration_ms))

    def percentiles(self, kind: str = "all") -> Dict[str, Any]:
        """Compute p50/p95/p99 for warm (cache-hit), cold (cache-miss), or all."""
        if kind == "warm":
            samples = list(self._warm)
        elif kind == "cold":
            samples = list(self._cold)
        else:
            samples = list(self._cold) + list(self._warm)

        if not samples:
            return {"count": 0, "p50_ms": None, "p95_ms": None, "p99_ms": None}

        samples.sort()
        n = len(samples)
        return {
            "count": n,
            "p50_ms": round(samples[int(0.50 * (n - 1))], 2),
            "p95_ms": round(samples[int(0.95 * (n - 1))], 2),
            "p99_ms": round(samples[int(0.99 * (n - 1))], 2),
            "min_ms": round(samples[0], 2),
            "max_ms": round(samples[-1], 2),
        }

    def summary(self) -> Dict[str, Any]:
        """Full summary: warm, cold, and combined."""
        return {
            "pipeline": self._name,
            "warm": self.percentiles("warm"),
            "cold": self.percentiles("cold"),
            "combined": self.percentiles("all"),
        }

    def reset(self) -> None:
        self._cold.clear()
        self._warm.clear()


class LatencyTimer:
    """Context manager that records elapsed time into a LatencyTracker on exit."""

    __slots__ = ("_tracker", "_cache_hit", "_t0")

    def __init__(self, tracker: LatencyTracker, *, cache_hit: bool = False):
        self._tracker = tracker
        self._cache_hit = cache_hit
        self._t0 = 0.0

    def __enter__(self) -> "LatencyTimer":
        self._t0 = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        elapsed = (time.perf_counter() - self._t0) * 1000.0
        self._tracker.record(elapsed, cache_hit=self._cache_hit)
        return False


# Module-level singleton for the recommend pipeline.
_recommend_tracker: Optional[LatencyTracker] = None


def get_recommend_tracker() -> LatencyTracker:
    """Get or create the singleton tracker for the recommend pipeline."""
    global _recommend_tracker
    if _recommend_tracker is None:
        _recommend_tracker = LatencyTracker("recommend")
    return _recommend_tracker
