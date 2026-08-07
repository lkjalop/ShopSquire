"""Safe internet search — guardrail tests (mock fetcher, no network)."""
from __future__ import annotations

from src.app.services.external_product_research_service import research


class _Fetcher:
    def __init__(self, hits):
        self.hits = hits
        self.seen_query = None
        self.seen_allowlist = None

    def fetch(self, scrubbed_query, *, allowlist, timeout_s=4.0):
        self.seen_query = scrubbed_query
        self.seen_allowlist = allowlist
        return self.hits


class _FakeRedis:
    def __init__(self):
        self.store = {}

    def get(self, k):
        return self.store.get(k)

    def setex(self, k, ttl, v):
        self.store[k] = v


_ALLOW = ["shop-reviews.example"]


def test_disabled_by_default():
    out = research("anything", fetcher=_Fetcher([{"source_domain": "shop-reviews.example"}]), allowlist=_ALLOW)
    assert out["status"] == "disabled" and out["items"] == []


def test_pii_scrubbed_before_egress():
    f = _Fetcher([])
    research("email me at bob@x.com", fetcher=f, allowlist=_ALLOW, enabled=True,
             scrub=lambda q: q.replace("bob@x.com", "[redacted]"))
    assert "bob@x.com" not in f.seen_query and "[redacted]" in f.seen_query


def test_allowlist_drops_non_allowlisted_domain():
    hits = [
        {"title": "Allowed", "source_domain": "shop-reviews.example"},
        {"title": "Evil", "source_domain": "evil.example"},
    ]
    out = research("laptops", fetcher=_Fetcher(hits), allowlist=_ALLOW, enabled=True)
    domains = {i["source_domain"] for i in out["items"]}
    assert domains == {"shop-reviews.example"}  # evil dropped even though fetcher returned it


def test_sku_gate_sold_here_vs_not_sold():
    hits = [
        {"title": "Acme Pro 15 review", "name": "Acme Pro 15", "source_domain": "shop-reviews.example"},
        {"title": "Some Other Brand X1", "name": "Other Brand X1", "source_domain": "shop-reviews.example"},
    ]
    out = research("acme", fetcher=_Fetcher(hits), allowlist=_ALLOW, enabled=True,
                   catalog_skus=["LAP-001"], catalog_names={"LAP-001": "Acme Pro 15"})
    by_title = {i["title"]: i for i in out["items"]}
    assert by_title["Acme Pro 15 review"]["sku"] == "LAP-001" and by_title["Acme Pro 15 review"]["sold_here"] is True
    nm = by_title["Some Other Brand X1"]
    assert nm["sku"] is None and nm["sold_here"] is False and nm["label"] == "not sold by this store"


def test_fetcher_error_fails_safe_with_status():
    class _Boom:
        def fetch(self, *a, **k):
            raise RuntimeError("network down")

    out = research("x", fetcher=_Boom(), allowlist=_ALLOW, enabled=True)
    assert out["status"] == "error" and out["items"] == []
    assert out["source_status"]["status"] == "error"


def test_empty_hits_status_empty_with_labeled_source():
    out = research("x", fetcher=_Fetcher([]), allowlist=_ALLOW, enabled=True)
    assert out["status"] == "empty"
    assert out["source_status"]["source"] == "external_research"


def test_cache_namespace_isolates_verticals():
    r = _FakeRedis()
    a = [{"title": "X", "source_domain": "shop-reviews.example"}]
    research("q", fetcher=_Fetcher(a), allowlist=_ALLOW, enabled=True, redis=r, cache_namespace="tA:electronics")
    # different namespace must NOT hit A's cache -> uses its own fetch
    out_b = research("q", fetcher=_Fetcher([{"title": "Y", "source_domain": "shop-reviews.example"}]),
                     allowlist=_ALLOW, enabled=True, redis=r, cache_namespace="tB:pharmacy")
    assert out_b["items"][0]["title"] == "Y"
    # same namespace -> cache hit (A's X), not the new fetch
    out_a2 = research("q", fetcher=_Fetcher([{"title": "Z", "source_domain": "shop-reviews.example"}]),
                      allowlist=_ALLOW, enabled=True, redis=r, cache_namespace="tA:electronics")
    assert out_a2["status"] == "cached" and out_a2["items"][0]["title"] == "X"


def test_allowlist_is_per_profile_no_bleed():
    from src.app.platform.store_profile import profile_slot, reset_active_profile_id, set_active_profile_id

    def _allow(pid):
        tok = set_active_profile_id(pid)
        try:
            return profile_slot("external_research_allowlist", default=None) or []
        finally:
            reset_active_profile_id(tok)

    el, ph = _allow("electronics"), _allow("pharmacy")
    assert "pcmag.com" in el and "pcmag.com" not in ph
    assert "drugs.com" in ph and "drugs.com" not in el


def test_no_item_is_sold_here_without_a_sku():
    hits = [{"title": "T", "name": "Unmapped", "source_domain": "shop-reviews.example"}]
    out = research("x", fetcher=_Fetcher(hits), allowlist=_ALLOW, enabled=True, catalog_names={"LAP-9": "Totally Different"})
    assert all((i["sku"] is not None) == i["sold_here"] for i in out["items"])
    assert out["items"][0]["sold_here"] is False


# ── run_external_research_stage (Phase 3 extraction) ──
def test_stage_returns_none_when_disabled(monkeypatch):
    from src.app.services.external_product_research_service import run_external_research_stage
    monkeypatch.delenv("EXTERNAL_RESEARCH_ENABLED", raising=False)
    assert run_external_research_stage(query="laptop", results=[], flags={"EXTERNAL_RESEARCH_ENABLED": False}) is None


def test_stage_reports_not_configured_when_no_provider_endpoint(monkeypatch):
    from src.app.services.external_product_research_service import run_external_research_stage
    monkeypatch.setenv("EXTERNAL_RESEARCH_ENABLED", "1")
    monkeypatch.delenv("EXTERNAL_RESEARCH_SEARCH_URL", raising=False)
    out = run_external_research_stage(
        query="laptop",
        results=[{"sku": "A", "name": "Alpha"}],
        flags={"EXTERNAL_RESEARCH_ALLOWLIST": ["trusted.com"]},
        tenant_id="tenant-a",
    )
    assert out is not None and out["items"] == []
    assert out["provider_id"] is None
    assert out["run_status"] == "not_configured"
    assert out["provider_attempts"][0]["status"] == "not_configured"


def test_stage_executes_only_a_tenant_allowed_capability_provider(monkeypatch):
    from src.app.services.external_product_research_service import run_external_research_stage
    from src.app.services.research_provider_registry import (
        ResearchProvider,
        ResearchProviderRegistry,
    )

    class ProviderFetcher:
        def fetch(self, _query, *, allowlist, timeout_s=4.0, cancellation=None):
            assert allowlist == ["vendor.example"]
            assert timeout_s == 1.2
            return [{
                "title": "Official requirements",
                "snippet": "Published compatibility information",
                "url": "https://vendor.example/requirements",
                "source_domain": "vendor.example",
            }]

    registry = ResearchProviderRegistry([ResearchProvider(
        provider_id="official-search",
        capabilities=("official_requirements",),
        allowed_tenants=("tenant-a",),
        allowed_domains=("vendor.example",),
        authority="official_source_index",
        fetcher_factory=ProviderFetcher,
        deadline_ms=1200,
    )])
    monkeypatch.setenv("EXTERNAL_RESEARCH_ENABLED", "1")

    out = run_external_research_stage(
        query="unfamiliar workload official requirements",
        tenant_id="tenant-a",
        buyer_consent=True,
        provider_registry=registry,
    )

    assert out is not None
    assert out["run_status"] == "ok"
    assert out["provider_id"] == "official-search"
    assert out["items"][0]["source_domain"] == "vendor.example"
    assert [item["status"] for item in out["provider_attempts"]] == ["selected", "ok"]
