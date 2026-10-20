from pathlib import Path
import pytest

from fastapi.testclient import TestClient

from src.app.main import create_app


@pytest.fixture(autouse=True)
def isolated_playbook_registry(tmp_path, monkeypatch):
    from src.app.services import playbook_engine as engine
    source = Path('config/security/cv_playbooks.json')
    isolated = tmp_path / 'cv_playbooks.json'
    isolated.write_bytes(source.read_bytes())
    monkeypatch.setattr(engine, '_playbooks_path', lambda: isolated)
    monkeypatch.setattr(engine, '_playbook_versions_path', lambda: tmp_path / 'versions')
    engine.load_playbook_config(force_reload=True)
    yield
    # The monkeypatched path is still valid here; invalidate without reading
    # another test's file after fixture teardown.
    with engine._CFG_CACHE_LOCK:
        engine._CFG_CACHE.clear()


def _owner_headers() -> dict:
    return {"x-api-key": "local-owner-key"}


def test_publish_requires_approval_then_succeeds():
    app = create_app()
    client = TestClient(app)

    req = {
        "playbook_id": "PB-PAYMENT-FRAUD",
        "updates": {"enabled": True},
    }
    r = client.post("/api/v1/admin/playbooks/publish", headers=_owner_headers(), json=req)
    assert r.status_code == 200
    body = r.json()
    assert body.get("status") == "pending_approval"
    aid = body.get("approval_id")
    assert aid

    a = client.post(f"/api/v1/approvals/{aid}/approve", headers=_owner_headers())
    assert a.status_code == 200

    req["approval_id"] = aid
    r2 = client.post("/api/v1/admin/playbooks/publish", headers=_owner_headers(), json=req)
    assert r2.status_code == 200
    body2 = r2.json()
    assert body2.get("status") == "ok"
    assert body2.get("playbook_id") == "PB-PAYMENT-FRAUD"


def test_rollback_requires_approval():
    app = create_app()
    client = TestClient(app)

    req = {
        "playbook_id": "PB-PAYMENT-FRAUD",
        "target_version": "1.0.0",
    }
    r = client.post("/api/v1/admin/playbooks/rollback", headers=_owner_headers(), json=req)
    assert r.status_code == 200
    assert r.json().get("status") == "pending_approval"


def test_approved_publish_rejects_changed_updates_without_writing_configuration():
    from src.app.services import playbook_engine

    client = TestClient(create_app())
    request = {"playbook_id": "PB-PAYMENT-FRAUD", "updates": {"enabled": True}}
    pending = client.post("/api/v1/admin/playbooks/publish", headers=_owner_headers(), json=request)
    assert pending.status_code == 200, pending.text
    approval_id = pending.json()["approval_id"]
    approved = client.post(f"/api/v1/approvals/{approval_id}/approve", headers=_owner_headers())
    assert approved.status_code == 200, approved.text
    before = playbook_engine._playbooks_path().read_bytes()
    changed = client.post("/api/v1/admin/playbooks/publish", headers=_owner_headers(),
        json={**request, "updates": {"enabled": False}, "approval_id": approval_id})
    assert changed.status_code == 409, changed.text
    assert changed.json()["detail"] == "approval_payload_mismatch"
    assert playbook_engine._playbooks_path().read_bytes() == before
