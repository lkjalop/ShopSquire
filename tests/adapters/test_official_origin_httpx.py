import asyncio
import hashlib

import httpx
import pytest

from src.app.adapters.official_origin_httpx import (
    AsyncGovernedOfficialOriginFetcher,
    GovernedOfficialOriginFetcher,
)


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


def test_redirects_are_validated_hop_by_hop_and_private_targets_are_rejected():
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

    assert redirect["error"] == "origin_redirect_domain_not_allowlisted"
    assert redirect["receipt"]["redirect_chain"][0]["to_host"] == "127.0.0.1"
    assert oversized["error"] == "origin_body_too_large"


def test_same_policy_redirect_is_followed_with_a_bounded_receipt():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/start":
            return httpx.Response(302, headers={"location": "/requirements"})
        return httpx.Response(
            200, text="Official requirements", headers={"content-type": "text/html"},
        )

    result = GovernedOfficialOriginFetcher(
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        resolver=_public_resolver,
    ).fetch("https://docs.example/start", allowlist=["docs.example"])

    assert result["status"] == "completed"
    assert result["url"] == "https://docs.example/requirements"
    assert result["receipt"]["redirect_count"] == 1
    assert result["receipt"]["redirect_chain"][0]["to_host"] == "docs.example"


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


def test_executable_mime_type_is_rejected_after_a_bounded_dispatch():
    result = GovernedOfficialOriginFetcher(
        client=httpx.Client(transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200, content=b"MZ-not-a-document",
                headers={"content-type": "application/octet-stream"},
            ),
        )),
        resolver=_public_resolver,
    ).fetch("https://docs.example/download", allowlist=["docs.example"])

    assert result["status"] == "failed"
    assert result["error"] == "origin_content_type_not_allowed"
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


@pytest.mark.asyncio
async def test_async_fetch_is_cancellable_during_active_origin_read():
    entered = asyncio.Event()

    async def slow_response(_request):
        entered.set()
        await asyncio.sleep(60)
        return httpx.Response(200, content=b"late", headers={"content-type": "text/html"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(slow_response))
    fetcher = AsyncGovernedOfficialOriginFetcher(client=client, resolver=_public_resolver)
    task = asyncio.create_task(fetcher.fetch_async(
        "https://csrc.nist.gov/doc", allowlist=["csrc.nist.gov"],
    ))
    await entered.wait()
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    else:
        raise AssertionError("active official-origin read ignored cancellation")
    await client.aclose()


@pytest.mark.asyncio
async def test_async_redirect_revalidates_destination_before_second_dispatch():
    calls = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(302, headers={"location": "http://127.0.0.1/private"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    result = await AsyncGovernedOfficialOriginFetcher(
        client=client, resolver=_public_resolver,
    ).fetch_async("https://docs.example/start", allowlist=["docs.example"])

    assert result["error"] == "origin_redirect_domain_not_allowlisted"
    assert calls == ["https://docs.example/start"]
    await client.aclose()
