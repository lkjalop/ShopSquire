"""An approved capability must authorize the exact reviewed configuration change."""
import json

import pytest
from fastapi import HTTPException

from src.app.routers import admin_playbooks as router


def _reviewed(monkeypatch, payload, *, capability="playbook_publish", status="approved"):
    monkeypatch.setattr(router, "_approval_status", lambda _: {
        "id": "approval", "capability": capability, "status": status, "payload": payload,
    })


@pytest.mark.parametrize("changed", [
    {"playbook_id": "PB-A", "updates": {"enabled": False}},
    {"playbook_id": "PB-B", "updates": {"enabled": True}},
    {"playbook_id": "PB-A", "updates": {"enabled": 1}},
    {"playbook_id": "PB-A", "updates": {"enabled": True, "new_action": "send"}},
])
def test_approved_publish_does_not_authorize_changed_payload(monkeypatch, changed):
    _reviewed(monkeypatch, json.dumps({"playbook_id": "PB-A", "updates": {"enabled": True}}))
    with pytest.raises(HTTPException) as failure:
        router._ensure_change_approval(approval_id="approval", capability="playbook_publish",
                                       approval_payload=changed, actor="owner")
    assert failure.value.status_code == 409
    assert failure.value.detail == "approval_payload_mismatch"


def test_rollback_approval_is_bound_to_its_target_version(monkeypatch):
    _reviewed(monkeypatch, {"playbook_id": "PB-A", "target_version": "1.0"}, capability="playbook_rollback")
    with pytest.raises(HTTPException) as failure:
        router._ensure_change_approval(approval_id="approval", capability="playbook_rollback",
            approval_payload={"playbook_id": "PB-A", "target_version": "2.0"}, actor="owner")
    assert failure.value.status_code == 409


@pytest.mark.parametrize("payload", [None, "broken-json", "[]"])
def test_approval_with_unreadable_reviewed_payload_cannot_execute(monkeypatch, payload):
    _reviewed(monkeypatch, payload)
    with pytest.raises(HTTPException) as failure:
        router._ensure_change_approval(approval_id="approval", capability="playbook_publish",
            approval_payload={"playbook_id": "PB-A", "updates": {"enabled": True}}, actor="owner")
    assert failure.value.status_code == 409


def test_same_reviewed_payload_ignores_object_key_order(monkeypatch):
    _reviewed(monkeypatch, '{"updates":{"enabled":true},"playbook_id":"PB-A"}')
    result = router._ensure_change_approval(approval_id="approval", capability="playbook_publish",
        approval_payload={"playbook_id": "PB-A", "updates": {"enabled": True}}, actor="owner")
    assert result["status"] == "approved"
