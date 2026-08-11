from fastapi.testclient import TestClient

from scripts.tool_bridge import app
from src.app.services.registry import get_tool_contract_fingerprint
from src.app.tools.runner import ToolRunner


def test_tool_contract_fingerprint_changes_when_reviewed_schema_changes(monkeypatch):
    from src.app.services import registry

    before = get_tool_contract_fingerprint("catalog.search")
    monkeypatch.setitem(registry._TOOL_META["catalog.search"], "input_schema", {"query": {"type": "string"}})
    after = get_tool_contract_fingerprint("catalog.search")
    assert before != after


def test_bridge_rejects_unreviewed_contract_change():
    response = TestClient(app).post("/tools/run", json={
        "tool": "catalog.search", "params": {"query": "laptop"}, "contract_hash": "unreviewed-change",
    })
    assert response.status_code == 409


def test_bridge_requires_configured_identity_when_enforced(monkeypatch):
    monkeypatch.setenv("TOOL_BRIDGE_AUTH_ENFORCE", "1")
    monkeypatch.delenv("TOOL_BRIDGE_TOKEN", raising=False)
    response = TestClient(app).post("/tools/run", json={"tool": "catalog.search", "params": {}})
    assert response.status_code == 503


def test_bridge_echoes_reviewed_contract_and_accepts_bearer_identity(monkeypatch):
    monkeypatch.setenv("TOOL_BRIDGE_TOKEN", "test-only-token")
    contract = get_tool_contract_fingerprint("inventory.check")
    response = TestClient(app).post(
        "/tools/run",
        headers={"Authorization": "Bearer test-only-token"},
        json={"tool": "inventory.check", "params": {"sku": "SKU-1"}, "tenant_id": "tenant-a", "contract_hash": contract},
    )
    assert response.status_code == 200
    assert response.json()["_tool_contract_hash"] == contract


def test_strict_runner_does_not_fallback_locally_after_bridge_security_failure(monkeypatch):
    monkeypatch.setenv("TOOL_BRIDGE_CONTRACT_ENFORCE", "1")
    runner = ToolRunner()
    monkeypatch.setattr(runner, "_bridge_call", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("tool_bridge_contract_mismatch")))
    monkeypatch.setattr(runner, "_local_tool", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("local fallback must not run")))
    result = runner.run("catalog.search", {"query": "laptop"}, tenant_id="tenant-a", trace_id="trace-a")
    assert result["status"] == "blocked"
    assert result["source"] == "bridge_security_boundary"
