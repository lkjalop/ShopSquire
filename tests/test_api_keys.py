import os

from fastapi.testclient import TestClient

from src.app.main import create_app
app = create_app()


def test_api_key_management(tmp_path, monkeypatch):
    keys_path = tmp_path / "api_keys.json"
    audit_path = tmp_path / "api_key_audit.jsonl"
    monkeypatch.setenv("API_KEYS_PATH", str(keys_path))
    monkeypatch.setenv("API_KEYS_AUDIT_PATH", str(audit_path))

    client = TestClient(app, headers={"x-api-key": os.getenv("OWNER_API_KEY", "local-owner-key")})

    r0 = client.get("/api/v1/admin/api-keys")
    assert r0.status_code == 200

    r1 = client.post("/api/v1/admin/api-keys", params={"target_role": "merchant", "key": "test-merchant-1"})
    assert r1.status_code == 200

    r2 = client.post("/api/v1/admin/api-keys/rotate", params={"target_role": "merchant"})
    assert r2.status_code == 200
    new_key = r2.json().get("key")
    assert new_key

    r3 = client.delete("/api/v1/admin/api-keys", params={"target_role": "merchant", "key": "test-merchant-1"})
    assert r3.status_code == 200

    ra = client.get("/api/v1/admin/api-keys/audit")
    assert ra.status_code == 200
    assert len(ra.json().get("events", [])) >= 3
