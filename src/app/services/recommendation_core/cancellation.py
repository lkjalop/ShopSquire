"""Request-scoped cooperative cancellation for synchronous recommendation stages."""
from __future__ import annotations

from dataclasses import dataclass, field
import threading
import time


class RecommendationCancelled(RuntimeError):
    """Raised only at safe stage boundaries after the buyer request has ended."""


@dataclass
class RecommendationCancellation:
    deadline_monotonic: float
    _event: threading.Event = field(default_factory=threading.Event, repr=False)
    reason: str | None = None

    @classmethod
    def with_timeout(cls, seconds: float) -> "RecommendationCancellation":
        return cls(time.monotonic() + max(0.01, float(seconds)))

    def cancel(self, reason: str) -> None:
        self.reason = str(reason or "request_cancelled")
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set() or time.monotonic() >= self.deadline_monotonic

    def raise_if_cancelled(self) -> None:
        if self.cancelled:
            raise RecommendationCancelled(self.reason or "request_deadline_exceeded")

