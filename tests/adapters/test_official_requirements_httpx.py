import httpx

from src.app.adapters.official_requirements_httpx import OfficialRequirementsHttpFetcher


def _resolver_public(_host, *_args, **_kwargs):
    return [(2, 1, 6, "", ("93.184.216.34", 0))]


def test_official_requirements_connector_returns_typed_candidates():
    seen = {}

    def handler(request):
        seen["authorization"] = request.headers.get("Authorization")
        return httpx.Response(200, json={"results": [{
            "title": "Official workstation requirements",
            "url": "https://docs.vendor.example/workstation",
            "snippet": "Current supported hardware requirements.",
            "claim_candidates": [{
                "claim_type": "recommended_requirements",
                "attribute_key": "ram_gb",
                "operator": ">=",
                "value": 32,
            }],
        }]})

    fetcher = OfficialRequirementsHttpFetcher(
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        endpoint_template="https://requirements.example/api?q={query}",
        resolver=_resolver_public,
        api_key="connector-secret",
    )

    rows = fetcher.fetch("simulation workstation", allowlist=["vendor.example"])

    assert rows[0]["source_domain"] == "docs.vendor.example"
    assert rows[0]["claim_candidates"][0]["attribute_key"] == "ram_gb"
    assert seen["authorization"] == "Bearer connector-secret"
