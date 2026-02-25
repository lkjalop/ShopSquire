from __future__ import annotations

from src.app.security.url_guard import validate_outbound_url


def test_blocks_localhost_and_metadata():
    ok1, _ = validate_outbound_url("http://localhost:8080/test")
    ok2, _ = validate_outbound_url("http://169.254.169.254/latest/meta-data")
    assert ok1 is False
    assert ok2 is False


def test_allows_public_https_domain():
    ok, reason = validate_outbound_url("https://example.com/path")
    # DNS may be unavailable in isolated runs; either allow or unresolved with allow.
    assert ok is True or reason in ("ok_unresolved",)

