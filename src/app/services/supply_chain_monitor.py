from __future__ import annotations

import math
import time
from typing import Dict, Any, List


class SupplyChainMonitor:
    """Lightweight 3-sigma anomaly detector for provider metrics.

    Tracks rolling windows for latency and error rates per provider.
    Use ingest_event() to feed observations, and detect_anomalies() to obtain flags.
    """

    def __init__(self, window_seconds: int = 3600):
        self.window_seconds = max(60, int(window_seconds))
        self._events: Dict[str, List[Dict[str, Any]]] = {}

    def ingest_event(self, provider: str, latency_ms: float | None, status: str | None, schema_ok: bool = True) -> None:
        now = time.time()
        if provider not in self._events:
            self._events[provider] = []
        self._events[provider].append({
            "ts": now,
            "latency_ms": float(latency_ms or 0.0),
            "status": str(status or "ok").lower(),
            "schema_ok": bool(schema_ok),
        })
        # Trim old
        cutoff = now - self.window_seconds
        self._events[provider] = [e for e in self._events[provider] if e.get("ts", now) >= cutoff]

    def _stats(self, provider: str) -> Dict[str, Any]:
        ev = self._events.get(provider, [])
        n = len(ev)
        lat = [e.get("latency_ms", 0.0) for e in ev]
        mean = (sum(lat) / float(max(1, n))) if n > 0 else 0.0
        var = (sum((x - mean) ** 2 for x in lat) / float(max(1, n))) if n > 0 else 0.0
        std = math.sqrt(var)
        err = sum(1 for e in ev if (e.get("status") or "ok") != "ok")
        schema_bad = sum(1 for e in ev if not bool(e.get("schema_ok", True)))
        return {
            "count": n,
            "lat_mean": mean,
            "lat_std": std,
            "error_rate": (float(err) / float(max(1, n))) if n > 0 else 0.0,
            "schema_error_rate": (float(schema_bad) / float(max(1, n))) if n > 0 else 0.0,
        }

    def detect_anomalies(self, provider: str, lat_threshold_ms: float = 2000.0, sigma: float = 3.0) -> Dict[str, Any]:
        s = self._stats(provider)
        mean = s["lat_mean"]
        std = s["lat_std"]
        upper = mean + sigma * std
        flags = []
        # Latency anomaly: if upper bound exceeds configured threshold
        if upper >= float(lat_threshold_ms):
            flags.append("latency_sigma_exceeded")
        # Error rate anomaly
        if s["error_rate"] >= 0.05:
            flags.append("error_rate_high")
        # Schema drift anomaly
        if s["schema_error_rate"] >= 0.01:
            flags.append("schema_drift")
        return {
            "provider": provider,
            "stats": s,
            "sigma_upper": upper,
            "flags": flags,
        }


# Singleton (best-effort for app scope)
_SC_MONITOR = SupplyChainMonitor(window_seconds=3600)

def get_monitor() -> SupplyChainMonitor:
    return _SC_MONITOR
