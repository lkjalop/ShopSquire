from fastapi.testclient import TestClient
import json
import os
from tests.utils import default_headers

from src.app.main import create_app


app = create_app()


client = TestClient(app, headers=default_headers())


def _write_flags(flags: dict):
    path = os.path.join("config", "feature_flags.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(flags, f, ensure_ascii=False, indent=2)


def test_kill_switch_blocks_pricing():
    _write_flags({"USE_AGENT_CAPABILITIES": True, "AGENT_ROLLOUT_PERCENT": 100, "CAPABILITIES": {"pricing": {"enabled": True, "rollout_percent": 100}}, "KILL_SWITCH": True})
    r = client.get("/api/v1/pricing/suggest", params={"uid": "u1", "cart_total_cents": 12000})
    assert r.status_code == 503


def test_rollout_gating():
    _write_flags({"USE_AGENT_CAPABILITIES": True, "AGENT_ROLLOUT_PERCENT": 0, "CAPABILITIES": {"pricing": {"enabled": True, "rollout_percent": 0}}, "KILL_SWITCH": False})
    r = client.get("/api/v1/pricing/suggest", params={"uid": "someuser", "cart_total_cents": 12000})
    assert r.status_code == 200
    body = r.json()
    assert body.get("eligible") is False