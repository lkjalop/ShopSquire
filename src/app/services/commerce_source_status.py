"""Typed SourceStatus (1.2) — make retrieval degradation answer-facing.

The retrieval legs (from_db / from_vector / from_caption) fail open and return
[] on both "no matching products" AND "index unavailable / errored". Metrics
already record the difference, but the ANSWER cannot — so a degraded answer
silently looks like an empty catalog. This typed status, returned alongside the
candidates, lets the trace/UI say "caption_rag: error" or "clip_visual: empty
index" instead of dropping the source silently.

Pure + dependency-free. Port of GridVerdict's SourceStatus contract.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Coverage states, most→least healthy.
FULL = "full"
PARTIAL = "partial"
EMPTY = "empty"
UNAVAILABLE = "unavailable"
ERROR = "error"


@dataclass
class SourceStatus:
    source: str
    status: str = EMPTY
    hit_count: int = 0
    latency_ms: int = 0
    error: str | None = None

    @property
    def degraded(self) -> bool:
        return self.status in (UNAVAILABLE, ERROR, PARTIAL)

    @property
    def safe_for_buyer(self) -> bool:
        # buyers see a plain fallback line, never the raw error
        return not self.error

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "status": self.status,
            "hit_count": self.hit_count,
            "latency_ms": self.latency_ms,
            "error": self.error,
        }

    @classmethod
    def from_hits(cls, source: str, hits: list, latency_ms: int) -> "SourceStatus":
        n = len(hits or [])
        return cls(source=source, status=FULL if n > 0 else EMPTY,
                   hit_count=n, latency_ms=int(latency_ms))

    @classmethod
    def errored(cls, source: str, error: str, latency_ms: int) -> "SourceStatus":
        return cls(source=source, status=ERROR, hit_count=0,
                   latency_ms=int(latency_ms), error=str(error)[:160])

    @classmethod
    def unavailable(cls, source: str, reason: str, latency_ms: int = 0) -> "SourceStatus":
        return cls(source=source, status=UNAVAILABLE, hit_count=0,
                   latency_ms=int(latency_ms), error=str(reason)[:160])


def degraded_sources(statuses: dict[str, SourceStatus]) -> list[dict[str, Any]]:
    """The degradation ledger — sources that errored/were unavailable/partial.
    Surface into the answer's missing_data so a degraded answer SAYS it degraded."""
    return [s.to_dict() for s in (statuses or {}).values() if s.degraded]
