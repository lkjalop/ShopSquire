from fastapi.testclient import TestClient

from src.app.main import create_app


def test_status_summary_and_api_v1_alias_return_same_contract():
    app = create_app()
    client = TestClient(app)

    root = client.get("/status/summary")
    assert root.status_code == 200
    body_root = root.json()
    assert body_root.get("status") == "ok"
    assert isinstance(body_root.get("email_xdr"), dict)
    assert "warnings" in (body_root.get("email_xdr") or {})
    assert "errors" in (body_root.get("email_xdr") or {})
    assert "outbound_anomalies" in body_root

    alias = client.get("/api/v1/status/summary")
    assert alias.status_code == 200
    body_alias = alias.json()
    assert body_alias.get("status") == "ok"
    assert isinstance(body_alias.get("email_xdr"), dict)
    assert "warnings" in (body_alias.get("email_xdr") or {})
    assert "errors" in (body_alias.get("email_xdr") or {})
    assert "outbound_anomalies" in body_alias

