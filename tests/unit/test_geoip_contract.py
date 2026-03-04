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
