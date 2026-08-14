"""Bounded request-scoped cancellation signals for synchronous research workers."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass


@dataclass
class _Signal:
    event: threading.Event
    expires_at: float
    reason: str | None = None


class ResearchCancellationRegistry:
    def __init__(self, *, ttl_seconds: float = 120.0) -> None:
        self._ttl = max(10.0, ttl_seconds)
        self._lock = threading.Lock()
        self._signals: dict[tuple[str, str, str], _Signal] = {}

    def _prune(self, now: float) -> None:
        for key in [key for key, value in self._signals.items() if value.expires_at <= now]:
            self._signals.pop(key, None)

    def register(self, tenant_id: str, case_id: str, execution_id: str) -> None:
        now = time.monotonic()
        key = (tenant_id, case_id, execution_id)
        with self._lock:
            self._prune(now)
            # A keepalive cancellation can beat the research request into the
            # worker. Preserve that tombstone instead of resurrecting work the
            # buyer has already left.
            signal = self._signals.get(key)
            if signal is None:
                self._signals[key] = _Signal(
                    event=threading.Event(), expires_at=now + self._ttl,
                )
            else:
                signal.expires_at = now + self._ttl

    def cancel(self, tenant_id: str, case_id: str, execution_id: str, reason: str) -> bool:
        now = time.monotonic()
        key = (tenant_id, case_id, execution_id)
        with self._lock:
            self._prune(now)
            signal = self._signals.get(key)
            if signal is None:
                signal = _Signal(event=threading.Event(), expires_at=now + self._ttl)
                self._signals[key] = signal
            signal.reason = reason
            signal.event.set()
            return True

    def cancelled(self, tenant_id: str, case_id: str, execution_id: str | None) -> bool:
        if not execution_id:
            return False
        now = time.monotonic()
        with self._lock:
            self._prune(now)
            signal = self._signals.get((tenant_id, case_id, execution_id))
            return bool(signal and signal.event.is_set())


DEFAULT_RESEARCH_CANCELLATIONS = ResearchCancellationRegistry()


__all__ = ["DEFAULT_RESEARCH_CANCELLATIONS", "ResearchCancellationRegistry"]
