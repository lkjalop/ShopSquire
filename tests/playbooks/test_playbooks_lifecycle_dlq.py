import os
import json
import uuid
import pytest
from pathlib import Path

from fastapi.testclient import TestClient

from src.app.main import create_app
from src.app.services.playbook_engine import (
    load_playbook_config,
    start_playbook_run,
    execute_typed_actions,
)
from src.app.models.db import db_session


_PLAYBOOKS_PATH = Path("config") / "security" / "cv_playbooks.json"


@pytest.fixture(autouse=True)
def _restore_playbooks_registry_after_test():
    original = None
    if _PLAYBOOKS_PATH.exists():
        original = _PLAYBOOKS_PATH.read_text(encoding="utf-8")
    yield
    if original is None:
        try:
            if _PLAYBOOKS_PATH.exists():
                _PLAYBOOKS_PATH.unlink()
        except Exception:
            pass
    else:
        _PLAYBOOKS_PATH.parent.mkdir(parents=True, exist_ok=True)
        _PLAYBOOKS_PATH.write_text(original, encoding="utf-8")
    # Ensure selector cache sees restored file for subsequent tests.
    try:
        load_playbook_config(force_reload=True)
    except Exception:
        pass


def _write_playbooks_config(tmp_pb_id: str) -> None:
    cfg = {
        "schema_version": "2.0",
        "risk_band_order": ["low", "medium", "high", "critical"],
        "playbooks": [
            {
                "id": tmp_pb_id,
                "title": "Test Playbook",
                "domain": "security",
                "priority": 10,
                "enabled": True,
                "version": "1.0.0",
                "trigger_logic": "any",
                "entry_conditions": {},
                "actions": [
                    {"type": "notify_ops", "params": {"channel": "email"}}
                ],
                "sla_minutes": 30,
                "risk_band_min": "low",
                "owners": ["owner@test"],
                "checks": [],
                "closure_criteria": [],
            }
        ],
        "signal_map": {"email_security": [tmp_pb_id]},
        "tag_map": {"dmarc_fail": [tmp_pb_id]},
    }
    path = os.path.join("config", "security", "cv_playbooks.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def test_playbook_publish_rollback_and_diff(tmp_path):
    pb_id = "PB-TEST-1"
    _write_playbooks_config(pb_id)
    app = create_app()
    client = TestClient(app)

    # Validate baseline config
    r = client.post("/api/v1/admin/playbooks/validate", json={}, headers={"x-api-key": "local-owner-key"})
    assert r.status_code == 200
    assert r.json().get("valid") is True

    # Publish change requires approval first
    r = client.post(
        "/api/v1/admin/playbooks/publish",
        json={"playbook_id": pb_id, "updates": {"title": "Updated Title"}, "actor": "tester"},
        headers={"x-api-key": "local-owner-key"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body.get("status") == "pending_approval"
    approval_id = body.get("approval_id")
    assert approval_id

    # Approve in DB then publish
    with db_session() as db:
        db.execute(
            "INSERT INTO approvals (id, capability, payload, reason, status, created_by) VALUES (:id,:cap,:p,:r,:s,:cb)",
            {
                "id": approval_id,
                "cap": "playbook_publish",
                "p": json.dumps({"playbook_id": pb_id}),
                "r": "unit-test",
                "s": "approved",
                "cb": "tester",
            },
        )
        db.commit()

    r2 = client.post(
        "/api/v1/admin/playbooks/publish",
        json={"playbook_id": pb_id, "updates": {"title": "Updated Title"}, "actor": "tester", "approval_id": approval_id},
        headers={"x-api-key": "local-owner-key"},
    )
    assert r2.status_code == 200
    pub = r2.json()
    assert pub.get("status") == "ok"
    before_v = (pub.get("before") or {}).get("version")
    after_v = (pub.get("after") or {}).get("version")
    assert before_v != after_v

    # Diff between previous and new version
    rd = client.get(f"/api/v1/admin/playbooks/{pb_id}/diff", params={"from_version": before_v, "to_version": after_v}, headers={"x-api-key": "local-owner-key"})
    assert rd.status_code == 200
    assert isinstance(rd.json().get("diff"), list)

    # Rollback requires approval first
    r3 = client.post(
        "/api/v1/admin/playbooks/rollback",
        json={"playbook_id": pb_id, "target_version": before_v, "actor": "tester"},
        headers={"x-api-key": "local-owner-key"},
    )
    assert r3.status_code == 200
    pend = r3.json()
    assert pend.get("status") == "pending_approval"
    rb_approval_id = pend.get("approval_id")
    assert rb_approval_id
    with db_session() as db:
        db.execute(
            "INSERT INTO approvals (id, capability, payload, reason, status, created_by) VALUES (:id,:cap,:p,:r,:s,:cb)",
            {
                "id": rb_approval_id,
                "cap": "playbook_rollback",
                "p": json.dumps({"playbook_id": pb_id, "target_version": before_v}),
                "r": "unit-test",
                "s": "approved",
                "cb": "tester",
            },
        )
        db.commit()

    r4 = client.post(
        "/api/v1/admin/playbooks/rollback",
        json={"playbook_id": pb_id, "target_version": before_v, "actor": "tester", "approval_id": rb_approval_id},
        headers={"x-api-key": "local-owner-key"},
    )
    assert r4.status_code == 200
    rb = r4.json()
    assert rb.get("after", {}).get("version") == before_v


def test_dlq_list_and_reprocess(monkeypatch):
    pb_id = "PB-TEST-2"
    _write_playbooks_config(pb_id)

    # Build a fake run
    cfg = load_playbook_config(force_reload=True)
    playbook = next((p for p in (cfg.get("playbooks") or []) if p.get("id") == pb_id), None)
    assert playbook is not None
    run_id = start_playbook_run(trace_id=str(uuid.uuid4()), decision_id=None, tenant_id="t1", playbook=playbook, owner="ops", metadata={"case": "x"})
    assert run_id

    # Force action failure to push to DLQ
    from src.app.services import playbook_engine as engine

    def boom(action, context):
        raise RuntimeError("boom")

    monkeypatch.setattr(engine, "_execute_action", boom)
    res = execute_typed_actions(run_id=run_id, actions=[{"type": "notify_ops", "params": {"channel": "email"}}], context={"tenant": "t1"})
    assert res.get("failed")

    app = create_app()
    client = TestClient(app)
    # DLQ should have at least one item
    dlq = client.get("/api/v1/admin/playbooks/ops/dlq", headers={"x-api-key": "local-owner-key"})
    assert dlq.status_code == 200
    items = dlq.json().get("items") or []
    assert len(items) >= 1

    # Reprocess after making action succeed
    def ok(action, context):
        return {"ok": True, "reprocessed": True, "provider": "unit"}

    monkeypatch.setattr(engine, "_execute_action", ok)
    r = client.post("/api/v1/admin/playbooks/ops/dlq/reprocess", json={"limit": 20}, headers={"x-api-key": "local-owner-key"})
    assert r.status_code == 200
    rp = r.json()
    assert rp.get("reprocessed", 0) >= 1
import os
import json
import pytest

from fastapi.testclient import TestClient

from src.app.main import create_app
from src.app.services.playbook_engine import start_playbook_run, execute_typed_actions


def _client():
    app = create_app()
    return TestClient(app)


def test_playbook_validate_publish_diff_and_rollback_flow(tmp_path):
    os.environ["TEST_SKIP_ADMIN_HEAVY"] = "1"
    pbid = "PB-EMAIL-001"
    _write_playbooks_config(pbid)
    c = _client()

    # Validate current config
    r = c.post("/api/v1/admin/playbooks/validate", json={}, headers={"x-api-key": "local-owner-key"})
    assert r.status_code == 200
    assert r.json().get("valid") is True

    # Publish requires approval; request update to PB-EMAIL-001 title
    r = c.post(
        "/api/v1/admin/playbooks/publish",
        json={"playbook_id": pbid, "updates": {"title": "Vendor Payout Change Verification (Updated)"}, "actor": "developer"},
        headers={"x-api-key": "local-owner-key"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data.get("status") == "pending_approval"
    approval_id = data.get("approval_id")
    assert approval_id

    # Approve the change
    r2 = c.post(f"/api/v1/approvals/{approval_id}/approve", headers={"x-api-key": "local-owner-key"})
    assert r2.status_code == 200

    # Publish again with approval; should apply and produce snapshot
    r3 = c.post(
        "/api/v1/admin/playbooks/publish",
        json={"playbook_id": pbid, "updates": {"title": "Vendor Payout Change Verification (Updated)"}, "actor": "developer", "approval_id": approval_id},
        headers={"x-api-key": "local-owner-key"},
    )
    assert r3.status_code == 200
    after = r3.json().get("after")
    before = r3.json().get("before")
    assert after and before and after.get("version") != before.get("version")

    # Diff between versions should have lines
    r4 = c.get(f"/api/v1/admin/playbooks/{pbid}/diff", params={"from_version": before.get("version"), "to_version": after.get("version")}, headers={"x-api-key": "local-owner-key"})
    assert r4.status_code == 200
    diff = r4.json().get("diff")
    assert isinstance(diff, list) and len(diff) > 0

    # Rollback requires approval
    r5 = c.post(
        "/api/v1/admin/playbooks/rollback",
        json={"playbook_id": pbid, "target_version": before.get("version"), "actor": "developer"},
        headers={"x-api-key": "local-owner-key"},
    )
    assert r5.status_code == 200
    assert r5.json().get("status") == "pending_approval"
    rid = r5.json().get("approval_id")
    assert rid

    # Approve rollback and apply
    r6 = c.post(f"/api/v1/approvals/{rid}/approve", headers={"x-api-key": "local-owner-key"})
    assert r6.status_code == 200
    r7 = c.post(
        "/api/v1/admin/playbooks/rollback",
        json={"playbook_id": pbid, "target_version": before.get("version"), "actor": "developer", "approval_id": rid},
        headers={"x-api-key": "local-owner-key"},
    )
    assert r7.status_code == 200
    rb = r7.json()
    assert rb.get("after", {}).get("version") == before.get("version")


def test_playbook_dlq_list_and_reprocess(monkeypatch):
    os.environ["TEST_SKIP_ADMIN_HEAVY"] = "1"
    os.environ["PLAYBOOK_ACTION_MAX_RETRIES"] = "0"
    c = _client()

    # Start a run for a known playbook
    run_id = start_playbook_run(trace_id=None, decision_id="dec-1", tenant_id="t1", playbook={"id": "PB-SEC-001", "version": "1.0.0"}, owner="owner", metadata={"ctx": "x"})
    assert run_id

    # Force an action failure to send to DLQ
    from src.app.services import playbook_engine as eng

    def _fail_action(action, context):
        raise RuntimeError("forced failure")

    monkeypatch.setattr(eng, "_execute_action", _fail_action, raising=False)
    res = execute_typed_actions(run_id=run_id, actions=[{"type": "force_fail", "mode": "automatic"}], context={})
    assert res["failed"]

    # List DLQ via admin endpoint
    r = c.get("/api/v1/admin/playbooks/ops/dlq", params={"limit": 10}, headers={"x-api-key": "local-owner-key"})
    assert r.status_code == 200
    items = r.json().get("items")
    assert isinstance(items, list) and len(items) >= 1

    # Patch action to succeed, then reprocess
    def _ok_action(action, context):
        return {"ok": True, "action_type": action.get("type")}

    monkeypatch.setattr(eng, "_execute_action", _ok_action, raising=False)
    r2 = c.post("/api/v1/admin/playbooks/ops/dlq/reprocess", json={"limit": 10}, headers={"x-api-key": "local-owner-key"})
    assert r2.status_code == 200
    rep = r2.json()
    assert int(rep.get("reprocessed") or 0) >= 1

    # DLQ should be reduced after reprocess
    r3 = c.get("/api/v1/admin/playbooks/ops/dlq", params={"limit": 10}, headers={"x-api-key": "local-owner-key"})
    assert r3.status_code == 200
    items2 = r3.json().get("items")
    assert isinstance(items2, list)
    assert len(items2) <= len(items)
