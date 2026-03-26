from fastapi.testclient import TestClient

from src.app.main import create_app


def test_merchant_email_lab_sets_inline_csp_and_csrf_cookie():
    client = TestClient(create_app())

    resp = client.get("/merchant/email-lab", headers={"host": "127.0.0.1:8080"})

    assert resp.status_code == 200
    csp = str(resp.headers.get("content-security-policy") or "")
    assert "script-src 'self' 'unsafe-inline'" in csp
    set_cookie = str(resp.headers.get("set-cookie") or "")
    assert "ss_csrf=" in set_cookie
    assert "submitEscalate()" in resp.text
