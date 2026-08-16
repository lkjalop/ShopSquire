"""Bounded reliability observations for replaceable search engines."""
from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
import os
import sqlite3
from threading import RLock
from typing import Any


@dataclass(frozen=True)
class EngineObservation:
    outcome: str
    latency_ms: float


class DiscoveryEngineReliability:
    def __init__(
        self,
        *,
        window_size: int = 20,
        minimum_attempts: int = 3,
        storage_path: str | None = None,
    ) -> None:
        self._window_size = max(3, int(window_size))
        self._minimum_attempts = max(2, int(minimum_attempts))
        self._storage_path = str(storage_path or "").strip() or None
        self._observations: dict[tuple[str, str], deque[EngineObservation]] = defaultdict(
            lambda: deque(maxlen=self._window_size),
        )
        self._lock = RLock()
        if self._storage_path:
            self._restore()

    def _connect(self) -> sqlite3.Connection:
        assert self._storage_path is not None
        connection = sqlite3.connect(self._storage_path, timeout=1.0)
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS discovery_engine_observation (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                endpoint TEXT NOT NULL,
                engine TEXT NOT NULL,
                outcome TEXT NOT NULL,
                latency_ms REAL NOT NULL,
                observed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """,
        )
        return connection

    def _restore(self) -> None:
        """Restore the bounded recent window; persistence is telemetry, never authority."""
        try:
            with self._connect() as connection:
                rows = connection.execute(
                    """
                    SELECT endpoint, engine, outcome, latency_ms
                    FROM discovery_engine_observation
                    ORDER BY id ASC
                    """,
                ).fetchall()
        except (OSError, sqlite3.Error):
            return
        for endpoint, engine, outcome, latency_ms in rows:
            self._observations[(str(endpoint), str(engine))].append(EngineObservation(
                outcome=str(outcome), latency_ms=max(0.0, float(latency_ms)),
            ))

    def _persist(self, rows: list[tuple[str, str, str, float]]) -> None:
        if not self._storage_path or not rows:
            return
        try:
            with self._connect() as connection:
                connection.executemany(
                    """
                    INSERT INTO discovery_engine_observation
                        (endpoint, engine, outcome, latency_ms)
                    VALUES (?, ?, ?, ?)
                    """,
                    rows,
                )
                for endpoint, engine, _outcome, _latency in rows:
                    connection.execute(
                        """
                        DELETE FROM discovery_engine_observation
                        WHERE endpoint = ? AND engine = ? AND id NOT IN (
                            SELECT id FROM discovery_engine_observation
                            WHERE endpoint = ? AND engine = ?
                            ORDER BY id DESC LIMIT ?
                        )
                        """,
                        (endpoint, engine, endpoint, engine, self._window_size),
                    )
        except (OSError, sqlite3.Error):
            # Search remains usable when optional telemetry persistence is unavailable.
            return

    def record(self, *, endpoint: str, receipt: dict[str, Any], latency_ms: float) -> None:
        from src.app.observability.pilot_runtime_metrics import discovery_engine_outcomes_total

        responded = {str(value) for value in receipt.get("engines_responded") or [] if str(value)}
        failures = {
            str(row.get("engine") or "")
            for row in receipt.get("engine_failures") or []
            if str(row.get("engine") or "")
        }
        queried = {
            str(value) for value in receipt.get("engines_queried") or [] if str(value)
        } or responded | failures
        persisted: list[tuple[str, str, str, float]] = []
        with self._lock:
            for engine in sorted(queried):
                outcome = (
                    "failure" if engine in failures
                    else "response" if engine in responded
                    else "zero_result"
                )
                bounded_latency = max(0.0, float(latency_ms))
                self._observations[(endpoint, engine)].append(EngineObservation(
                    outcome=outcome, latency_ms=bounded_latency,
                ))
                discovery_engine_outcomes_total.labels(outcome=outcome).inc()
                persisted.append((endpoint, engine, outcome, bounded_latency))
        self._persist(persisted)

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


DEFAULT_DISCOVERY_ENGINE_RELIABILITY = DiscoveryEngineReliability(
    storage_path=os.getenv("DISCOVERY_ENGINE_RELIABILITY_DB_PATH"),
)
