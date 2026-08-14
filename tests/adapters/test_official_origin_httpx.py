import hashlib

import httpx

from src.app.adapters.official_origin_httpx import GovernedOfficialOriginFetcher


def _public_resolver(_host, *_args, **_kwargs):
    return [(2, 1, 6, "", ("93.184.216.34", 0))]


def test_fetches_allowlisted_origin_and_records_real_network_receipt():
    body = b"<html><body>Official requirements</body></html>"
    fetcher = GovernedOfficialOriginFetcher(
        client=httpx.Client(transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200, content=body, headers={"content-type": "text/html; charset=utf-8"},
            )
        )),
        resolver=_public_resolver,
    )

    result = fetcher.fetch(
        "https://docs.factoryio.com/manual/system-requirements/",
        allowlist=["docs.factoryio.com"],
        certification_run_id="cert-123",
    )

    assert result["status"] == "completed"
    assert result["authority"] == "untrusted_origin_content_pending_compilation"
    assert result["receipt"]["fixture"] is False
    assert result["receipt"]["network_execution"] is True
    assert result["receipt"]["paid_calls"] == 0
    assert result["receipt"]["response_body_hash"] == hashlib.sha256(body).hexdigest()
    assert result["receipt"]["external_call_dispatched"] is True
    assert result["receipt"]["certification_run_id"] == "cert-123"


def test_rejects_non_allowlisted_and_private_origins_before_dispatch():
    calls = []
    client = httpx.Client(transport=httpx.MockTransport(
        lambda request: calls.append(request) or httpx.Response(200, text="not reached"),
    ))
    non_allowlisted = GovernedOfficialOriginFetcher(
        client=client, resolver=_public_resolver,
    ).fetch("https://evil.example/", allowlist=["nist.gov"])
    private = GovernedOfficialOriginFetcher(
        client=client,
        resolver=lambda *_args, **_kwargs: [(2, 1, 6, "", ("127.0.0.1", 0))],
    ).fetch("https://csrc.nist.gov/pubs/ir/8356/final", allowlist=["csrc.nist.gov"])

    assert non_allowlisted["error"] == "origin_domain_not_allowlisted"
    assert private["error"] == "origin_host_not_public"
    assert non_allowlisted["receipt"]["network_execution"] is False
    assert private["receipt"]["network_execution"] is False
    assert calls == []


def test_redirect_and_oversized_body_are_not_accepted_as_evidence():
    redirect = GovernedOfficialOriginFetcher(
        client=httpx.Client(transport=httpx.MockTransport(
            lambda _request: httpx.Response(302, headers={"location": "http://127.0.0.1/"}),
        )),
        resolver=_public_resolver,
    ).fetch("https://csrc.nist.gov/start", allowlist=["csrc.nist.gov"])
    oversized = GovernedOfficialOriginFetcher(
        client=httpx.Client(transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200, content=b"x" * 2048, headers={"content-type": "text/html"},
            ),
        )),
        resolver=_public_resolver,
        max_bytes=1024,
    ).fetch("https://csrc.nist.gov/doc", allowlist=["csrc.nist.gov"])

    assert redirect["error"] == "origin_http_status"
    assert oversized["error"] == "origin_body_too_large"


def test_transport_timeout_is_recorded_as_dispatched_network_work():
    def timeout(_request):
        raise httpx.ReadTimeout("publisher did not respond")

    result = GovernedOfficialOriginFetcher(
        client=httpx.Client(transport=httpx.MockTransport(timeout)),
        resolver=_public_resolver,
    ).fetch("https://csrc.nist.gov/doc", allowlist=["csrc.nist.gov"])

    assert result["status"] == "failed"
    assert result["error"] == "origin_transport_error:ReadTimeout"
    assert result["receipt"]["network_execution"] is True
    assert result["receipt"]["external_call_dispatched"] is True


def test_certification_timeout_is_inert_in_production_and_explicit_in_dev(monkeypatch):
    calls = []
    client = httpx.Client(transport=httpx.MockTransport(
        lambda request: calls.append(request) or httpx.Response(
            200, content=b"requirements", headers={"content-type": "text/html"},
        )
    ))
    monkeypatch.setenv("RESEARCH_CERTIFICATION_MODE", "1")
    monkeypatch.setenv("RESEARCH_CERTIFICATION_FAULT_PROFILE", "publisher_timeout")
    monkeypatch.setenv("APP_ENV", "development")

    result = GovernedOfficialOriginFetcher(
        client=client, resolver=_public_resolver,
    ).fetch("https://csrc.nist.gov/doc", allowlist=["csrc.nist.gov"])

    assert calls == []
    assert result["error"] == "certification_injected_publisher_timeout"
    assert result["receipt"]["fixture"] is True
    assert result["receipt"]["external_call_dispatched"] is False
