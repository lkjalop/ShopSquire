"""Bounded tenant-scoped cache for compiled official-origin evidence."""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from threading import RLock
from typing import Any
from urllib.parse import urlparse


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class OfficialEvidenceCacheKey:
    tenant_id: str
    source_id: str
    canonical_url: str
    content_hash: str
    parser_version: str
    policy_version: str

    def __post_init__(self) -> None:
        bounded = {
            "tenant_id": (self.tenant_id, 160),
            "source_id": (self.source_id, 160),
            "canonical_url": (self.canonical_url, 1000),
            "content_hash": (self.content_hash, 128),
            "parser_version": (self.parser_version, 200),
            "policy_version": (self.policy_version, 200),
        }
        if any(not value or len(value) > limit for value, limit in bounded.values()):
            raise ValueError("official_evidence_cache_key_invalid")
        if len(self.content_hash) < 8:
            raise ValueError("official_evidence_content_hash_invalid")
        parsed = urlparse(self.canonical_url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise ValueError("official_evidence_canonical_url_invalid")


@dataclass(frozen=True)
class OfficialEvidenceCacheEntry:
    key: OfficialEvidenceCacheKey
    content_type: str
    observed_at: datetime
    freshness_sla_hours: int
    claims: tuple[dict[str, Any], ...]
    context_claims: tuple[dict[str, Any], ...]

    def __post_init__(self) -> None:
        if not 1 <= int(self.freshness_sla_hours) <= 8760:
            raise ValueError("official_evidence_freshness_sla_invalid")
        if len(self.claims) > 256 or len(self.context_claims) > 128:
            raise ValueError("official_evidence_claim_set_too_large")

    def fresh_at(self, now: datetime) -> bool:
        return _utc(now) <= _utc(self.observed_at) + timedelta(
            hours=self.freshness_sla_hours,
        )


class OfficialEvidenceCache:
    """In-memory first implementation with explicit bounds and immutable entries."""

    def __init__(self, *, max_entries: int = 256) -> None:
        self._max_entries = max(1, min(int(max_entries), 4096))
        self._entries: OrderedDict[OfficialEvidenceCacheKey, OfficialEvidenceCacheEntry] = (
            OrderedDict()
        )
        self._lock = RLock()

    def put(self, entry: OfficialEvidenceCacheEntry) -> None:
        with self._lock:
            self._entries.pop(entry.key, None)
            self._entries[entry.key] = entry
            while len(self._entries) > self._max_entries:
                self._entries.popitem(last=False)

    def get_latest(
        self,
        *,
        tenant_id: str,
        source_id: str,
        canonical_url: str | None,
        parser_version: str,
        policy_version: str,
        now: datetime | None = None,
    ) -> tuple[OfficialEvidenceCacheEntry | None, str]:
        current = _utc(now or datetime.now(timezone.utc))
        with self._lock:
            matches = [
                entry for key, entry in self._entries.items()
                if (
                    key.tenant_id == tenant_id
                    and key.source_id == source_id
                    and (canonical_url is None or key.canonical_url == canonical_url)
                    and key.parser_version == parser_version
                    and key.policy_version == policy_version
                )
            ]
            if not matches:
                return None, "miss"
            entry = max(matches, key=lambda item: item.observed_at)
            self._entries.move_to_end(entry.key)
            return (entry, "fresh_hit") if entry.fresh_at(current) else (entry, "stale_revalidate")

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)


DEFAULT_OFFICIAL_EVIDENCE_CACHE = OfficialEvidenceCache()


__all__ = [
    "DEFAULT_OFFICIAL_EVIDENCE_CACHE",
    "OfficialEvidenceCache",
    "OfficialEvidenceCacheEntry",
    "OfficialEvidenceCacheKey",
]
