import os
import json
from src.app.security.observer import _geoip_enrich


def test_cidr_override_match_unit(tmp_path):
    overrides = {
        "overrides": [
            {"cidr": "203.0.113.0/24", "asn": 64500, "org": "TestVPN", "country": "US", "is_vpn": True, "is_hosting": True, "risk": 0.95}
        ]
    }
    cfg_dir = tmp_path / "config" / "security"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "geoip_overrides.json").write_text(json.dumps(overrides), encoding="utf-8")
    (cfg_dir / "bad_asn.json").write_text(json.dumps({"bad_asn": [64500]}), encoding="utf-8")

    old_cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        geo = _geoip_enrich("203.0.113.5")
        assert geo.get("asn") == 64500
        assert geo.get("matched_override") or geo.get("is_hosting") or geo.get("is_vpn")
        assert float(geo.get("risk", 0.0)) >= 0.9
    finally:
        os.chdir(old_cwd)


def test_provider_fallback_graceful_unit():
    geo = _geoip_enrich("198.51.100.23")
    assert isinstance(geo, dict)
