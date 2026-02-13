import os

from fastapi.testclient import TestClient

from src.app.main import create_app


def test_safe_link_rewrite_and_allow_redirect(monkeypatch):
    os.environ["MERCHANT_API_KEY"] = "local-merchant-key"
    app = create_app()
    client = TestClient(app)

    monkeypatch.setattr("src.app.services.safe_links.enrich_iocs", lambda *a, **k: {"malicious_hits": 0})
    monkeypatch.setattr("src.app.services.safe_links.detonate_targets", lambda *a, **k: {"malicious": False, "score": 0.0})

    r = client.post(
        "/api/v1/safe-links/rewrite",
        headers={"x-api-key": "local-merchant-key"},
        json={"tenant_id": "t-safe", "url": "https://example.com/invoice/1"},
    )
    assert r.status_code == 200
    token = r.json().get("token")
    assert token

    c = client.get(f"/api/v1/safe-links/r/{token}", follow_redirects=False)
    assert c.status_code == 307
    assert "example.com/invoice/1" in str(c.headers.get("location") or "")


def test_safe_link_click_blocked_on_recheck(monkeypatch):
    os.environ["MERCHANT_API_KEY"] = "local-merchant-key"
    app = create_app()
    client = TestClient(app)

    monkeypatch.setattr("src.app.services.safe_links.enrich_iocs", lambda *a, **k: {"malicious_hits": 1})
    monkeypatch.setattr("src.app.services.safe_links.detonate_targets", lambda *a, **k: {"malicious": True, "score": 0.9})

    r = client.post(
        "/api/v1/safe-links/rewrite",
        headers={"x-api-key": "local-merchant-key"},
        json={"tenant_id": "t-safe", "url": "https://evil.example/phish"},
    )
    token = r.json().get("token")
    c = client.get(f"/api/v1/safe-links/r/{token}")
    assert c.status_code == 423
    body = c.json()
    assert body.get("ok") is False
    assert body.get("verdict") == "block"

