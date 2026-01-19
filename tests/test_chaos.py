import time
from fastapi.testclient import TestClient

from src.app.main import app
from src.app.config import get_settings

client = TestClient(app)


def _write_flags(flags):
    settings = get_settings()
    with open(settings.feature_flags_path, "w", encoding="utf-8") as f:
        import json
        json.dump(flags, f, ensure_ascii=False, indent=2)


def test_chaos_latency_injection():
    _write_flags({
        "USE_AGENT_CAPABILITIES": True,
        "AGENT_ROLLOUT_PERCENT": 100,
        "CAPABILITIES": {"pricing": {"enabled": True, "rollout_percent": 100}},
        "KILL_SWITCH": False,
        "CHAOS": {"enabled": True, "latency_ms": 200, "probability": 1.0}
    })
    start = time.time()
    r = client.get("/api/v1/pricing/suggest", params={"uid": "chaos", "cart_total_cents": 12000})
    assert r.status_code == 200
    elapsed = time.time() - start
    # Expect at least 0.15s due to chaos latency
    assert elapsed >= 0.15


def test_no_chaos_latency_when_disabled():
    _write_flags({
        "USE_AGENT_CAPABILITIES": True,
        "AGENT_ROLLOUT_PERCENT": 100,
        "CAPABILITIES": {"pricing": {"enabled": True, "rollout_percent": 100}},
        "KILL_SWITCH": False,
        "CHAOS": {"enabled": False}
    })
    start = time.time()
    r = client.get("/api/v1/pricing/suggest", params={"uid": "normal", "cart_total_cents": 12000})
    assert r.status_code == 200
    elapsed = time.time() - start
    assert elapsed < 0.15
