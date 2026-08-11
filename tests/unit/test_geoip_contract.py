from src.app.services import geoip


def test_geoip_module_exports_lookup_contract():
    assert hasattr(geoip, "lookup")
    assert callable(geoip.lookup)
    assert hasattr(geoip, "enrich_ip")
    assert callable(geoip.enrich_ip)


def test_geoip_lookup_returns_object_shape_from_enrich_dict(monkeypatch):
    monkeypatch.setattr(
        geoip,
        "enrich_ip",
        lambda ip: {
            "asn": 64512,
            "asn_org": "ExampleNet",
            "country": "us",
            "is_hosting": True,
            "is_vpn": False,
            "risk": 0.75,
            "matched_override": False,
        },
        raising=True,
    )
    out = geoip.lookup("203.0.113.10")
    assert out is not None
    assert out.asn == 64512
    assert out.asn_org == "ExampleNet"
    assert out.country == "US"
    assert out.is_hosting is True
    assert out.is_vpn is False
    assert float(out.risk) == 0.75


def test_external_geoip_lookup_is_opt_in(monkeypatch):
    monkeypatch.delenv("GEOIP_ALLOW_NETWORK_LOOKUP", raising=False)
    monkeypatch.setenv("IP2LOCATION_API_KEY", "must-not-be-used")

    assert geoip._ip2location_lookup("8.8.8.8") is None
    assert geoip._ip_api_lookup("8.8.8.8") is None


def test_unavailable_lookup_reports_source_health(monkeypatch):
    monkeypatch.setattr(geoip, "_mmdb_lookup", lambda ip: None)
    monkeypatch.setattr(geoip, "_offline_heuristic_lookup", lambda ip: None)
    monkeypatch.setattr(geoip, "_ip2location_lookup", lambda ip: None)
    monkeypatch.setattr(geoip, "_ip_api_lookup", lambda ip: None)
    monkeypatch.setattr(geoip, "_cache", geoip._TTLCache())

    result = geoip.enrich_ip("100.64.0.1")

    assert result["lookup_status"] == "unavailable"
    assert result["provider"] == "none"
    assert result["country"] is None
