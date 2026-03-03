import uuid

from fastapi.testclient import TestClient

from src.app.main import create_app
from src.app.services.playbook_engine import execute_typed_actions


def _owner_headers():
    return {"x-api-key": "local-owner-key"}


def test_typed_action_adapters_execute():
    run_id = f"run:{uuid.uuid4()}"
    actions = [
        {"type": "send_email", "params": {"to": "ops@example.com", "subject": "x", "body": "y"}},
        {"type": "create_return_label", "params": {"case_id": "case-123"}},
        {"type": "erp_signal_check", "params": {"order_id": "ORD-1"}},
    ]
    out = execute_typed_actions(run_id=run_id, actions=actions, context={"tenant_id": "t1"})
    assert len(out.get("executed") or []) >= 2
    assert len(out.get("failed") or []) == 0


def test_typed_actions_support_branching_and_looping():
    run_id = f"run:{uuid.uuid4()}"
    actions = [
        {
            "type": "if",
            "condition": {"path": "risk.score", "op": "gte", "value": 0.8},
            "then": [{"type": "notify_ops", "params": {"channel": "pager"}}],
            "else": [{"type": "notify_ops", "params": {"channel": "email"}}],
        },
        {
            "type": "for_each",
            "items_path": "targets",
            "item_var": "target",
            "do": [{"type": "notify_ops", "params": {"channel": "email"}}],
        },
    ]
    out = execute_typed_actions(
        run_id=run_id,
        actions=actions,
        context={"risk": {"score": 0.9}, "targets": ["a", "b"]},
    )
    assert len(out.get("failed") or []) == 0
    assert len(out.get("branches") or []) >= 2
    assert len(out.get("executed") or []) >= 3


def test_playbook_ops_stream_and_dlq_routes():
    app = create_app()
    client = TestClient(app)
    h = _owner_headers()

    r1 = client.get("/api/v1/admin/playbooks/ops/dlq?limit=10", headers=h)
    assert r1.status_code == 200
    body1 = r1.json()
    assert "items" in body1

    r2 = client.post("/api/v1/admin/playbooks/ops/dlq/reprocess", json={"limit": 5}, headers=h)
    assert r2.status_code == 200
    body2 = r2.json()
    assert "picked" in body2

    r3 = client.get("/api/v1/admin/playbooks/ops/streams/health", headers=h)
    assert r3.status_code == 200
    body3 = r3.json()
    assert "enabled" in body3

    r4 = client.post("/api/v1/admin/playbooks/ops/streams/recover", json={"count": 5}, headers=h)
    assert r4.status_code == 200
    body4 = r4.json()
    assert "recovered" in body4 or body4.get("status") in ("disabled", "redis_unavailable")

    r5 = client.post("/api/v1/admin/playbooks/ops/streams/replay", json={"count": 5}, headers=h)
    assert r5.status_code == 200
    body5 = r5.json()
    assert "replayed" in body5 or body5.get("status") in ("disabled", "redis_unavailable")

    r6 = client.get("/api/v1/admin/playbooks/ops/llm/routing?window_minutes=60", headers=h)
    assert r6.status_code == 200
    body6 = r6.json()
    assert "by_provider" in body6
    assert "series" in body6

    r7 = client.get("/api/v1/admin/playbooks/ops/llm/routing?window_minutes=60&tenant_id=tenant-a", headers=h)
    assert r7.status_code == 200
    body7 = r7.json()
    assert body7.get("tenant_id") == "tenant-a"

    r8 = client.post("/api/v1/admin/playbooks/ops/scheduler/run_cycle", headers=h)
    assert r8.status_code == 200
    body8 = r8.json()
    assert "checked" in body8

    r9 = client.post(
        "/api/v1/admin/playbooks/ops/debate/run",
        json={"scenario": "supplier_change", "proposal": {"action": "allow"}, "evidence": {"bank_account_changed": True}},
        headers=h,
    )
    assert r9.status_code == 200
    body9 = r9.json()
    assert "judge" in body9
