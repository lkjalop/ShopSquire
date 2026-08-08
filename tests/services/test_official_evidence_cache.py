from datetime import datetime, timezone

from src.app.services.official_evidence_cache import (
    OfficialEvidenceCache,
    OfficialEvidenceCacheEntry,
    OfficialEvidenceCacheKey,
)


def _entry(
    content_hash: str,
    *,
    tenant_id: str = "tenant-a",
    parser_version: str = "parser-v1",
    observed_hour: int = 0,
) -> OfficialEvidenceCacheEntry:
    return OfficialEvidenceCacheEntry(
        key=OfficialEvidenceCacheKey(
            tenant_id=tenant_id,
            source_id="official-source",
            canonical_url="https://official.example/requirements",
            content_hash=content_hash,
            parser_version=parser_version,
            policy_version="policy-v1",
        ),
        content_type="text/html",
        observed_at=datetime(2026, 8, 8, observed_hour, tzinfo=timezone.utc),
        freshness_sla_hours=24,
        claims=({"claim_id": content_hash},),
        context_claims=(),
    )


def test_cache_identity_is_tenant_source_url_parser_and_policy_scoped() -> None:
    cache = OfficialEvidenceCache()
    cache.put(_entry("a" * 64))
    common = {
        "source_id": "official-source",
        "canonical_url": "https://official.example/requirements",
        "policy_version": "policy-v1",
        "now": datetime(2026, 8, 8, 1, tzinfo=timezone.utc),
    }
    assert cache.get_latest(
        tenant_id="tenant-a", parser_version="parser-v1", **common,
    )[1] == "fresh_hit"
    without_known_canonical = {**common, "canonical_url": None}
    assert cache.get_latest(
        tenant_id="tenant-a", parser_version="parser-v1", **without_known_canonical,
    )[1] == "fresh_hit"
    assert cache.get_latest(
        tenant_id="tenant-b", parser_version="parser-v1", **common,
    ) == (None, "miss")
    assert cache.get_latest(
        tenant_id="tenant-a", parser_version="parser-v2", **common,
    ) == (None, "miss")


def test_cache_retains_content_hash_versions_and_returns_latest_fresh_entry() -> None:
    cache = OfficialEvidenceCache()
    cache.put(_entry("a" * 64, observed_hour=0))
    cache.put(_entry("b" * 64, observed_hour=2))
    entry, status = cache.get_latest(
        tenant_id="tenant-a", source_id="official-source",
        canonical_url="https://official.example/requirements",
        parser_version="parser-v1", policy_version="policy-v1",
        now=datetime(2026, 8, 8, 3, tzinfo=timezone.utc),
    )
    assert status == "fresh_hit"
    assert entry is not None
    assert entry.key.content_hash == "b" * 64
    assert len(cache) == 2


def test_cache_reports_stale_and_evicts_oldest_at_its_bound() -> None:
    cache = OfficialEvidenceCache(max_entries=1)
    cache.put(_entry("a" * 64, observed_hour=0))
    cache.put(_entry("b" * 64, observed_hour=1))
    assert len(cache) == 1
    entry, status = cache.get_latest(
        tenant_id="tenant-a", source_id="official-source",
        canonical_url="https://official.example/requirements",
        parser_version="parser-v1", policy_version="policy-v1",
        now=datetime(2026, 8, 10, 2, tzinfo=timezone.utc),
    )
    assert entry is not None
    assert entry.key.content_hash == "b" * 64
    assert status == "stale_revalidate"
