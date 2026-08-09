"""Track 5 — HttpxResearchFetcher: SSRF-safe, allowlist-enforced, never raises.

All hermetic: an injected httpx.MockTransport stands in for the network and a fake resolver stands
in for DNS, so the SSRF guard and allowlist filtering are tested without touching the wire.
"""
from __future__ import annotations

import json

import httpx

from src.app.adapters.external_research_httpx import HttpxResearchFetcher, _domain_allowed, _host_is_safe
from src.app.ports.external_product_research import ExternalResearchFetcher

_TEMPLATE = "https://search.example.com/api?q={query}"


def _resolver_public(host, *a, **k):
    return [(2, 1, 6, "", ("93.184.216.34", 0))]  # a public address


def _resolver_private(host, *a, **k):
    return [(2, 1, 6, "", ("127.0.0.1", 0))]


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def _ok_results(results):
    def handler(request):
        return httpx.Response(200, json={"results": results})
    return handler


# ── port conformance ──
def test_is_an_external_research_fetcher():
    assert isinstance(HttpxResearchFetcher(), ExternalResearchFetcher)


# ── inert until configured ──
def test_no_template_returns_empty():
    f = HttpxResearchFetcher(search_url_template="", resolver=_resolver_public)
    assert f.fetch("laptop", allowlist=["example.com"]) == []


def test_blank_query_returns_empty():
    f = HttpxResearchFetcher(client=_client(_ok_results([])), search_url_template=_TEMPLATE, resolver=_resolver_public)
    assert f.fetch("   ", allowlist=["example.com"]) == []


# ── happy path + allowlist filtering ──
def test_happy_path_parses_and_filters_to_allowlist():
    results = [
        {
            "title": "Good Laptop",
            "url": "https://shop.trusted.com/p/1",
            "content": "spec text",
            "claim_candidates": [{"attribute_key": "ram_gb", "value": 32}],
        },
        {"title": "Evil", "url": "https://evil.com/x", "snippet": "nope"},
        {"title": "No domain", "url": "not-a-url"},
    ]
    f = HttpxResearchFetcher(client=_client(_ok_results(results)), search_url_template=_TEMPLATE, resolver=_resolver_public)
    out = f.fetch("laptop", allowlist=["trusted.com"])
    assert len(out) == 1
    hit = out[0]
    assert hit["source_domain"] == "shop.trusted.com"  # subdomain of an allowlisted domain
    assert hit["title"] == "Good Laptop" and hit["snippet"] == "spec text"
    assert hit["url"] == "https://shop.trusted.com/p/1"
    assert hit["claim_candidates"] == [{"attribute_key": "ram_gb", "value": 32}]
    receipt = f.last_receipt
    assert receipt["fixture"] is False
    assert receipt["network_execution"] is True
    assert receipt["execution_status"] == "completed"
    assert receipt["provider_endpoint_host"] == "search.example.com"
    assert receipt["http_status"] == 200
    assert receipt["response_body_hash"]
    assert receipt["external_call_dispatched"] is True


def test_searxng_engine_degradation_is_recorded_separately_from_results():
    def handler(request):
        assert request.url.params["engines"] == "mojeek,bing"
        return httpx.Response(200, json={
            "results": [
                {"title": "Official", "url": "https://trusted.com/requirements", "engine": "bing"},
                {"title": "Other", "url": "https://other.example/page", "engine": "mojeek"},
            ],
            "unresponsive_engines": [
                ["brave", "too many requests"], ["startpage", "Suspended: CAPTCHA"],
            ],
        })

    fetcher = HttpxResearchFetcher(
        client=_client(handler),
        search_url_template="https://search.example.com/api?q={query}&engines=mojeek,bing",
        resolver=_resolver_public,
    )
    assert len(fetcher.fetch("requirements", allowlist=["trusted.com"])) == 1
    receipt = fetcher.last_receipt
    assert receipt["raw_result_count"] == 2
    assert receipt["allowlisted_result_count"] == 1
    assert receipt["engines_queried"] == ["mojeek", "bing"]
    assert receipt["engines_responded"] == ["bing", "mojeek"]
    assert receipt["engine_failures"] == [
        {"engine": "brave", "reason": "too many requests"},
        {"engine": "startpage", "reason": "Suspended: CAPTCHA"},
    ]
    assert set(receipt["degradation_reasons"]) == {
        "engines_captcha", "engines_rate_limited",
    }
    assert receipt["provider_status"] == "degraded"


def test_zero_allowlisted_results_is_not_reported_as_successful_evidence():
    fetcher = HttpxResearchFetcher(
        client=_client(_ok_results([{
            "title": "Off-domain", "url": "https://other.example/page", "engine": "bing",
        }])),
        search_url_template="https://search.example.com/api?q={query}&engines=mojeek,bing",
        resolver=_resolver_public,
    )
    assert fetcher.fetch("requirements", allowlist=["trusted.com"]) == []
    assert fetcher.last_receipt["execution_status"] == "completed"
    assert fetcher.last_receipt["provider_status"] == "degraded"
    assert fetcher.last_receipt["degradation_reasons"] == ["zero_allowlisted_results"]


def test_research_service_projects_discovery_transport_receipt():
    from src.app.services.external_product_research_service import research

    fetcher = HttpxResearchFetcher(
        client=_client(_ok_results([{
            "title": "Official requirements",
            "url": "https://trusted.com/requirements",
        }])),
        search_url_template=_TEMPLATE,
        resolver=_resolver_public,
    )

    result = research(
        "bounded query", fetcher=fetcher, allowlist=["trusted.com"], enabled=True,
    )

    assert result["transport_receipt"]["network_execution"] is True
    assert result["transport_receipt"]["fixture"] is False
    assert result["transport_receipt"]["query_hash"]


def test_bare_list_payload_supported():
    results = [{"title": "X", "url": "https://trusted.com/a", "description": "d"}]
    def handler(request):
        return httpx.Response(200, text=json.dumps(results))
    f = HttpxResearchFetcher(client=_client(handler), search_url_template=_TEMPLATE, resolver=_resolver_public)
    out = f.fetch("q", allowlist=["trusted.com"])
    assert len(out) == 1 and out[0]["snippet"] == "d"


# ── SSRF defenses ──
def test_private_host_blocked_no_request_made():
    def handler(request):  # must never be called
        raise AssertionError("request made to an SSRF-unsafe host")
    f = HttpxResearchFetcher(client=_client(handler), search_url_template=_TEMPLATE, resolver=_resolver_private)
    assert f.fetch("q", allowlist=["trusted.com"]) == []


def test_non_http_scheme_blocked():
    def handler(request):
        raise AssertionError("request made for a non-http scheme")
    f = HttpxResearchFetcher(client=_client(handler), search_url_template="file:///etc/passwd?x={query}",
                             resolver=_resolver_public)
    assert f.fetch("q", allowlist=["trusted.com"]) == []


def test_allow_private_opt_in_permits_localhost():
    results = [{"title": "Local", "url": "https://trusted.com/a"}]
    f = HttpxResearchFetcher(client=_client(_ok_results(results)), search_url_template=_TEMPLATE,
                             resolver=_resolver_private, allow_private=True)
    assert len(f.fetch("q", allowlist=["trusted.com"])) == 1


# ── error handling (never raises) ──
def test_redirect_not_followed_yields_empty():
    def handler(request):
        return httpx.Response(302, headers={"location": "http://169.254.169.254/latest/meta-data"})
    f = HttpxResearchFetcher(client=_client(handler), search_url_template=_TEMPLATE, resolver=_resolver_public)
    assert f.fetch("q", allowlist=["trusted.com"]) == []


def test_http_error_status_returns_empty():
    def handler(request):
        return httpx.Response(500, text="boom")
    f = HttpxResearchFetcher(client=_client(handler), search_url_template=_TEMPLATE, resolver=_resolver_public)
    assert f.fetch("q", allowlist=["trusted.com"]) == []


def test_non_json_body_returns_empty_not_raise():
    def handler(request):
        return httpx.Response(200, text="<html>not json</html>")
    f = HttpxResearchFetcher(client=_client(handler), search_url_template=_TEMPLATE, resolver=_resolver_public)
    assert f.fetch("q", allowlist=["trusted.com"]) == []


# ── unit guards ──
def test_host_is_safe_unit():
    assert _host_is_safe("ok.com", resolver=_resolver_public) is True
    assert _host_is_safe("ok.com", resolver=_resolver_private) is False
    assert _host_is_safe("", resolver=_resolver_public) is False
    # link-local (cloud metadata) and reserved are refused
    assert _host_is_safe("meta", resolver=lambda h, *a, **k: [(2, 1, 6, "", ("169.254.169.254", 0))]) is False


def test_domain_allowed_subdomain_match():
    assert _domain_allowed("a.b.trusted.com", ["trusted.com"]) is True
    assert _domain_allowed("trusted.com", ["trusted.com"]) is True
    assert _domain_allowed("nottrusted.com", ["trusted.com"]) is False
    assert _domain_allowed("eviltrusted.com", ["trusted.com"]) is False


# ── plugs into the guardrailed service ──
def test_plugs_into_research_service_with_sku_gate():
    from src.app.services.external_product_research_service import research

    results = [
        {"title": "Acme Widget 9000", "url": "https://trusted.com/w", "content": "great widget"},
        {"title": "Mystery Item", "url": "https://trusted.com/m", "content": "unknown"},
    ]
    fetcher = HttpxResearchFetcher(client=_client(_ok_results(results)), search_url_template=_TEMPLATE,
                                   resolver=_resolver_public)
    out = research(
        "widget", fetcher=fetcher, allowlist=["trusted.com"], enabled=True,
        catalog_skus=["SKU-1"], catalog_names={"SKU-1": "Acme Widget 9000"},
    )
    assert out["status"] == "ok" and len(out["items"]) == 2
    by_title = {i["title"]: i for i in out["items"]}
    assert by_title["Acme Widget 9000"]["sku"] == "SKU-1" and by_title["Acme Widget 9000"]["sold_here"] is True
    assert by_title["Mystery Item"]["sku"] is None and by_title["Mystery Item"]["label"] == "not sold by this store"
