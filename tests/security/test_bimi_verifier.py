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

