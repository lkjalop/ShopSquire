from fastapi.testclient import TestClient
from tests.utils import default_headers


from src.app.main import create_app


app = create_app()


client = TestClient(app, headers=default_headers())


def test_kill_switch_blocks_pricing(monkeypatch):
    flags = {"USE_AGENT_CAPABILITIES": True, "AGENT_ROLLOUT_PERCENT": 100, "CAPABILITIES": {"pricing": {"enabled": True, "rollout_percent": 100}}, "KILL_SWITCH": True}
    monkeypatch.setattr("src.app.routers.pricing._ff_get_flags", lambda: flags)
    r = client.get("/api/v1/pricing/suggest", params={"uid": "u1", "cart_total_cents": 12000})
    assert r.status_code == 503


def test_rollout_gating(monkeypatch):
    flags = {"USE_AGENT_CAPABILITIES": True, "AGENT_ROLLOUT_PERCENT": 0, "CAPABILITIES": {"pricing": {"enabled": True, "rollout_percent": 0}}, "KILL_SWITCH": False}
    monkeypatch.setattr("src.app.routers.pricing._ff_get_flags", lambda: flags)
    r = client.get("/api/v1/pricing/suggest", params={"uid": "someuser", "cart_total_cents": 12000})
    assert r.status_code == 200
    body = r.json()
    assert body.get("eligible") is False


def test_autonomy_scope_blocks_support(monkeypatch):
    flags = {
            "USE_AGENT_CAPABILITIES": True,
            "KILL_SWITCH": False,
            "AUTONOMY": {
                "kill_switch": False,
                "scopes": {
                    "support": {
                        "disabled": True,
                        "reason": "manual review freeze for showcase",
                    }
                },
            },
        }
    monkeypatch.setattr("src.app.routers.support._ff_get_flags", lambda: flags)
    r = client.post("/api/v1/support/answer", params={"question": "where is my order?"})
    assert r.status_code == 503
    body = r.json()
    detail = body.get("detail") if isinstance(body, dict) else {}
    assert detail.get("error") == "autonomy_kill_switch"
    assert detail.get("scope") == "support"
