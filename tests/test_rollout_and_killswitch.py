from fastapi.testclient import TestClient
import json
import os
from tests.utils import default_headers

import pytest

from src.app.main import create_app


app = create_app()


client = TestClient(app, headers=default_headers())


_FLAGS_PATH = os.path.join("config", "feature_flags.json")
try:
    with open(_FLAGS_PATH, "r", encoding="utf-8") as _f:
        _ORIGINAL_FLAGS = _f.read()
except Exception:
    _ORIGINAL_FLAGS = ""


def _write_flags(flags: dict):
    with open(_FLAGS_PATH, "w", encoding="utf-8") as f:
        json.dump(flags, f, ensure_ascii=False, indent=2)


@pytest.fixture(autouse=True)
def _restore_flags():
    yield
    with open(_FLAGS_PATH, "w", encoding="utf-8") as f:
        f.write(_ORIGINAL_FLAGS)


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


def test_autonomy_scope_blocks_support():
    _write_flags(
        {
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
    )
    r = client.post("/api/v1/support/answer", params={"question": "where is my order?"})
    assert r.status_code == 503
    body = r.json()
    detail = body.get("detail") if isinstance(body, dict) else {}
    assert detail.get("error") == "autonomy_kill_switch"
    assert detail.get("scope") == "support"
