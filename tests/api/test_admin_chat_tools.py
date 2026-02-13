import os
from fastapi.testclient import TestClient


def _make_app():
    # Relax security middleware for local tests
    os.environ.setdefault("DISABLE_SECURITY_MIDDLEWARE", "1")
    from src.app.main import create_app
    return create_app()


def test_admin_chat_tools_endpoints_smoke():
    app = _make_app()
    client = TestClient(app)

    # Rules evaluate
    r = client.post(
        "/api/v1/admin/tools/rules/evaluate",
        json={"query": "return fraud", "context": {"total": 100}},
    )
    assert r.status_code == 200
    j = r.json()
    assert "result" in j

    # Policy check
    r = client.post(
        "/api/v1/admin/tools/policy/check",
        json={"action": "approve", "reason": "manual"},
    )
    assert r.status_code == 200
    j = r.json()
    assert "verdict" in j and j["verdict"] in ("allow", "block", "escalate")

    # Create ticket
    r = client.post(
        "/api/v1/admin/tools/tickets/create",
        json={"title": "Smoke Ticket", "description": "test", "severity": "low"},
    )
    assert r.status_code == 200
    j = r.json()
    assert "id" in j
