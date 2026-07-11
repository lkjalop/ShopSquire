"""Shared postflight: session writeback (the multi-turn memory the facade reads) + telemetry,
best-effort and round-trippable through the facade's session reader."""
import json

from src.app.services import recommendation_facade as F
from src.app.services.recommendation_postflight import run_postflight, write_session
from src.app.services.recommendation_core.envelope import CoreResponse, ProductCard, TurnEnvelope


class _Redis:
    def __init__(self): self.store = {}
    def get(self, k): return self.store.get(k)
    def setex(self, k, ttl, v): self.store[k] = v
    def set(self, k, v): self.store[k] = v


def _env(**o):
    return TurnEnvelope.from_suggest_params(query="gaming laptop", uid="u1", tenant_id="t1", **o)


def _core(env, **o):
    c = CoreResponse(envelope=env, lane="SEARCH",
                     products=[ProductCard(sku="LAP-1", title="X"), ProductCard(sku="LAP-2", title="Y")])
    c.extras["decision"] = {"node_handle": "el-6-6", "requirements": {"ram_gb": [">=", 16]}}
    c.extras["intent"] = {"use_cases": ["gaming"]}
    for k, v in o.items():
        setattr(c, k, v)
    return c


def test_session_write_roundtrips_through_facade_reader():
    r = _Redis()
    env = _env(budget_max=2000)
    assert write_session(r, env, _core(env)) is True
    # the facade reads it back next turn (tenant-scoped key)
    slice_ = F._read_session_slice(r, "u1", "t1")
    assert slice_["prior_node"] == "el-6-6" and slice_["shortlist_skus"] == ["LAP-1", "LAP-2"]
    # persisted content is complete for prior-subject resolution
    raw = json.loads(r.store["session:t1:u1:kv_state"])
    assert raw["last_lane"] == "SEARCH" and raw["constraints"]["use_cases"] == ["gaming"]
    assert raw["constraints"]["budget_max_cents"] == 200000


def test_session_write_is_tenant_scoped():
    r = _Redis()
    env = _env()
    write_session(r, env, _core(env))
    assert "session:t1:u1:kv_state" in r.store          # not session:u1:...
    assert F._read_session_slice(r, "u1", "t2") == {}    # different tenant → isolated


def test_postflight_never_raises_and_reports():
    out = run_postflight(None, _env(), _core(_env()), latency_ms=42)   # redis=None
    assert out["session_written"] is False               # no redis → no write, no raise
    r = _Redis(); env = _env()
    out = run_postflight(r, env, _core(env), latency_ms=42)
    assert out["session_written"] is True


def test_no_uid_skips_write():
    r = _Redis()
    env = TurnEnvelope.from_suggest_params(query="x", uid="", tenant_id="t1")
    assert write_session(r, env, _core(env)) is False
