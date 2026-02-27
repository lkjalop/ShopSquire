from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from src.app.main import create_app


def test_flag_dual_approval_flow(monkeypatch):
    monkeypatch.setenv("FLAG_DUAL_APPROVAL_ENABLED", "1")
    monkeypatch.setenv("FLAG_APPROVALS_PATH", "tmp/flag_change_approvals.test.json")

    app = create_app()
    client = TestClient(app)

    flags_path = Path("config/feature_flags.json")
    original = flags_path.read_text(encoding="utf-8")

    try:
        baseline = json.loads(original)
        changed = dict(baseline)
        changed["KILL_SWITCH"] = not bool(baseline.get("KILL_SWITCH", False))

        propose = client.post(
            "/api/v1/admin/flags",
            json=changed,
            headers={"x-api-key": "local-owner-key", "X-Forwarded-User": "owner-a"},
        )
        assert propose.status_code == 200
        p = propose.json()
        assert p.get("pending_approval") is True
        proposal_id = str(p.get("proposal_id") or "")
        assert proposal_id

        same_actor = client.post(
            f"/api/v1/admin/flags/approvals/{proposal_id}/approve",
            headers={"x-api-key": "local-owner-key", "X-Forwarded-User": "owner-a"},
        )
        assert same_actor.status_code == 409

        approve = client.post(
            f"/api/v1/admin/flags/approvals/{proposal_id}/approve",
            headers={"x-api-key": "local-owner-key", "X-Forwarded-User": "owner-b"},
        )
        assert approve.status_code == 200
        assert approve.json().get("approved") is True

        apply_change = client.post(
            "/api/v1/admin/flags",
            json=changed,
            headers={
                "x-api-key": "local-owner-key",
                "X-Forwarded-User": "owner-b",
                "X-Flag-Approval-Id": proposal_id,
            },
        )
        assert apply_change.status_code == 200
        assert apply_change.json().get("updated") is True
    finally:
        flags_path.write_text(original, encoding="utf-8")
