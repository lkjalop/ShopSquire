"""Bounded, process-local reliability observations for replaceable search engines."""
from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from threading import RLock
from typing import Any


@dataclass(frozen=True)
class EngineObservation:
    outcome: str
    latency_ms: float


class DiscoveryEngineReliability:
    def __init__(self, *, window_size: int = 20, minimum_attempts: int = 3) -> None:
        self._window_size = max(3, int(window_size))
        self._minimum_attempts = max(2, int(minimum_attempts))
        self._observations: dict[tuple[str, str], deque[EngineObservation]] = defaultdict(
            lambda: deque(maxlen=self._window_size),
        )
        self._lock = RLock()

    def record(self, *, endpoint: str, receipt: dict[str, Any], latency_ms: float) -> None:
        responded = {str(value) for value in receipt.get("engines_responded") or [] if str(value)}
        failures = {
            str(row.get("engine") or "")
            for row in receipt.get("engine_failures") or []
            if str(row.get("engine") or "")
        }
        queried = {
            str(value) for value in receipt.get("engines_queried") or [] if str(value)
        } or responded | failures
        with self._lock:
            for engine in sorted(queried):
                outcome = (
                    "failure" if engine in failures
                    else "response" if engine in responded
                    else "zero_result"
                )
                self._observations[(endpoint, engine)].append(EngineObservation(
                    outcome=outcome, latency_ms=max(0.0, float(latency_ms)),
                ))

    def snapshots(self, endpoint: str) -> list[dict[str, Any]]:
        with self._lock:
            engines = sorted(engine for host, engine in self._observations if host == endpoint)
            rows = []
            for engine in engines:
                observations = list(self._observations[(endpoint, engine)])
                attempts = len(observations)
                responses = sum(row.outcome == "response" for row in observations)
                failures = sum(row.outcome == "failure" for row in observations)
                zero_results = sum(row.outcome == "zero_result" for row in observations)
                unhealthy_rate = (failures + zero_results) / attempts if attempts else 0.0
                rows.append({
                    "engine": engine,
                    "attempts": attempts,
                    "responses": responses,
                    "failures": failures,
                    "zero_results": zero_results,
                    "average_latency_ms": round(
                        sum(row.latency_ms for row in observations) / attempts, 3,
                    ) if attempts else 0.0,
                    "unhealthy_rate": round(unhealthy_rate, 4),
                    "suppressed": attempts >= self._minimum_attempts and unhealthy_rate >= 2 / 3,
                })
            return rows

    def recommended_engines(self, endpoint: str) -> list[str]:
        rows = self.snapshots(endpoint)
        healthy = [row["engine"] for row in rows if not row["suppressed"]]
        # Never suppress the entire discovery capability.
        return healthy or [row["engine"] for row in rows]


DEFAULT_DISCOVERY_ENGINE_RELIABILITY = DiscoveryEngineReliability()
