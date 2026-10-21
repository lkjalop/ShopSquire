import httpx
import pytest

from src.app.services.return_partner_integrations import (
    PartnerEndpoint,
    ValidatedReturnPartnerClient,
    validate_partner_endpoint,
)


def _public_dns(*_args):
    return [(None, None, None, None, ("8.8.8.8", 443))]


@pytest.fixture(autouse=True)
def allow_mock_partner_host():
    from src.app.security.egress_allowlist import scoped_egress_domains
    with scoped_egress_domains(['carrier.example.test']):
        yield


def test_network_policy_denial_is_a_typed_non_authorizing_outcome():
    from src.app.security.egress_allowlist import EgressBlockedError
    observed = []
    def denied(request):
        observed.append(str(request.url))
        raise EgressBlockedError(str(request.url))
    with httpx.Client(transport=httpx.MockTransport(denied)) as transport:
        client=ValidatedReturnPartnerClient(_endpoint(),client=transport,resolver=_public_dns)
        result=client.request(operation='return_label',path='/returns/labels',payload={},idempotency_key='denied-test')
        assert not transport.is_closed
    assert result.status=='policy_denied'
    assert result.detail=='outbound_policy_denied'
    assert result.provider_reference is None
    assert result.authority=='provider_observation'
    assert observed == ['https://carrier.example.test/v1/returns/labels']


def test_injected_redirect_following_client_cannot_visit_a_private_target():
    observed = []
    def redirect(request):
        observed.append(str(request.url))
        if len(observed) == 1:
            return httpx.Response(302, headers={'location': 'http://127.0.0.1/admin'})
        return httpx.Response(200, json={
            'status': 'confirmed', 'tracking_number': 'foreign-response',
            'label_url': 'https://labels.example.test/label/foreign',
        })
    with httpx.Client(transport=httpx.MockTransport(redirect), follow_redirects=True) as transport:
        client = ValidatedReturnPartnerClient(_endpoint(), client=transport, resolver=_public_dns)
        result = client.request(operation='return_label', path='/returns/labels',
            payload={}, idempotency_key='redirect-test')
        assert not transport.is_closed
    assert result.status == 'invalid_response'
    assert result.detail == 'partner_redirect_rejected'
    assert result.authority == 'provider_observation'
    assert observed == ['https://carrier.example.test/v1/returns/labels']


def _endpoint(**overrides):
    values = {
        "provider_id": "carrier-approved-1",
        "base_url": "https://carrier.example.test/v1",
        "allowed_hosts": ("carrier.example.test",),
        "bearer_token": "secret",
    }
    values.update(overrides)
    return PartnerEndpoint(**values)


def test_endpoint_must_be_operator_allowlisted_https_and_public():
    with pytest.raises(ValueError, match="https"):
        validate_partner_endpoint(
            _endpoint(base_url="http://carrier.example.test"), resolver=_public_dns
        )
    with pytest.raises(ValueError, match="allowlisted"):
        validate_partner_endpoint(
            _endpoint(allowed_hosts=("other.example.test",)), resolver=_public_dns
        )
    with pytest.raises(ValueError, match="publicly_routable"):
        validate_partner_endpoint(
            _endpoint(),
            resolver=lambda *_: [(None, None, None, None, ("127.0.0.1", 443))],
        )


def test_confirmed_label_is_bounded_typed_observation_not_commercial_authority():
    def handler(request: httpx.Request):
        assert request.headers["idempotency-key"] == "claim-12345678"
        return httpx.Response(200, json={
            "status": "confirmed",
            "id": "provider-ref",
            "tracking_number": "TRACK-1",
            "label_url": "https://labels.example.test/label/1",
        })

    client = ValidatedReturnPartnerClient(
        _endpoint(),
        client=httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False),
        resolver=_public_dns,
    )
    result = client.request(
        operation="return_label",
        path="/returns/labels",
        payload={"claim_id": "claim-1"},
        idempotency_key="claim-12345678",
    )
    assert result.status == "confirmed"
    assert result.provider_id == "carrier-approved-1"
    assert result.authority == "provider_observation"


@pytest.mark.parametrize(
    ("response", "detail"),
    [
        (httpx.Response(302, headers={"location": "http://127.0.0.1/admin"}), "redirect"),
        (httpx.Response(200, text="not-json"), "Expecting value"),
        (httpx.Response(200, json={"status": "refunded"}), "status_invalid"),
        (httpx.Response(200, json={"status": "confirmed"}), "incomplete"),
    ],
)
def test_untrusted_partner_responses_fail_typed_without_authorizing_an_outcome(response, detail):
    client = ValidatedReturnPartnerClient(
        _endpoint(),
        client=httpx.Client(transport=httpx.MockTransport(lambda _request: response)),
        resolver=_public_dns,
    )
    result = client.request(
        operation="return_label",
        path="/returns/labels",
        payload={"claim_id": "claim-1"},
        idempotency_key="claim-12345678",
    )
    assert result.status == "invalid_response"
    assert detail in str(result.detail)
    assert result.authority == "provider_observation"
