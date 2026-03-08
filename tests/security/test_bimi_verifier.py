from src.app.security.bimi_verifier import verify_bimi_provider_backed


def test_bimi_verifier_handles_minimal_payload():
    out = verify_bimi_provider_backed(
        {
            "from_addr": "billing@example.com",
            "bimi_present": True,
            "bimi_result": "pass",
            "bimi_location": "https://example.com/logo.svg",
        }
    )
    assert "verified" in out
    assert "failed" in out
    assert out.get("from_domain") == "example.com"
    assert isinstance(out.get("visual_similarity"), dict)


def test_bimi_visual_similarity_brand_mismatch():
    out = verify_bimi_provider_backed(
        {
            "from_addr": "billing@micros0ft.com",
            "vendor_domain": "microsoft.com",
            "bimi_present": True,
            "bimi_result": "pass",
            "bimi_location": "https://micros0ft.com/logo.svg",
        }
    )
    visual = out.get("visual_similarity") or {}
    assert visual.get("enabled") is True
    assert float(visual.get("brand_spoof_score") or 0.0) >= 0.72
    assert bool(visual.get("spoof_suspected")) is True
