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


def test_no_item_is_sold_here_without_a_sku():
    hits = [{"title": "T", "name": "Unmapped", "source_domain": "shop-reviews.example"}]
    out = research("x", fetcher=_Fetcher(hits), allowlist=_ALLOW, enabled=True, catalog_names={"LAP-9": "Totally Different"})
    assert all((i["sku"] is not None) == i["sold_here"] for i in out["items"])
    assert out["items"][0]["sold_here"] is False
