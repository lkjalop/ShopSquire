from fastapi.testclient import TestClient

from src.app.main import create_app


def test_policy_pack_release_create_list_get_verify():
    app = create_app()
    client = TestClient(app)

    create = client.post(
        "/api/v1/admin/email_security/policy-pack/release",
        json={"signer": "sec-eng", "changelog": ["Added ransomware artifact pack", "Added explainability card"]},
        headers={"x-api-key": "local-owner-key"},
    )
    assert create.status_code == 200
    body = create.json()
    rel = body.get("release") or {}
    assert body.get("ok") is True
    assert isinstance(rel.get("manifest"), dict)
    assert isinstance((rel.get("release_notes") or {}).get("changelog"), list)
    assert isinstance(rel.get("signature"), dict)
    assert (rel.get("verification") or {}).get("ok") is True

    version = str((rel.get("manifest") or {}).get("version") or "")
    assert version

    ls = client.get("/api/v1/admin/email_security/policy-pack/releases?limit=10", headers={"x-api-key": "local-owner-key"})
    assert ls.status_code == 200
    items = ls.json().get("items") or []
    assert isinstance(items, list)
    assert any(str((x.get("version") or "")) == version for x in items)

    one = client.get(f"/api/v1/admin/email_security/policy-pack/releases/{version}", headers={"x-api-key": "local-owner-key"})
    assert one.status_code == 200
    one_body = one.json()
    assert one_body.get("version") == version
    assert (one_body.get("verification") or {}).get("ok") is True
