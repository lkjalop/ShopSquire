"""The consolidated intelligence stage (services/recommend_intelligence_stage.py).

Verifies the three blocks compose + gate correctly with a fake mem and the global db_session engine:
all-flags-off → no-op; capture-on writes a decision; market-intel-on annotates; never raises.
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from src.app.services.recommend_intelligence_stage import IntelligenceStageState, run_intelligence_stage


class _FakeMem:
    def __init__(self):
        self.store = {}

    def get_kv(self, uid):
        return dict(self.store.get(uid) or {})

    def set_kv(self, uid, kv):
        self.store[uid] = dict(kv)


@pytest.fixture()
def aligned_engine(monkeypatch):
    eng = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False},
                        poolclass=StaticPool, future=True)
    import src.app.models.db as _dbmod
    orig = _dbmod.engine
    _dbmod.engine = eng
    _dbmod.set_engine(eng)
    with eng.begin() as c:
        from src.app.services import attribution
        # ensure attribution tables exist on this engine
    from src.app.models.db import db_session
    with db_session() as db:
        from src.app.services import attribution
        attribution.ensure_tables(db)
        db.commit()
    yield eng
    _dbmod.engine = orig
    _dbmod.set_engine(orig)


def _state(**over):
    base = dict(results=[{"sku": "A", "score": 0.9}], payload={}, flags={}, simulate=False,
                uid="u1", uid_hash="h1", query="laptop", constraints={}, kv={}, proposal={},
                trace_id="T1", decision_id="D1")
    base.update(over)
    return IntelligenceStageState(**base)


def test_all_off_is_noop(aligned_engine):
    st = _state(flags={"ATTRIBUTION_ENABLED": False})
    out = run_intelligence_stage(st, mem=_FakeMem())
    assert out == st.results
    assert st.payload == {} and "ranking_experiment" not in st.payload


def test_capture_writes_decision(aligned_engine):
    st = _state(flags={"ATTRIBUTION_ENABLED": True})
    run_intelligence_stage(st, mem=_FakeMem())
    from src.app.models.db import db_session
    with db_session() as db:
        row = db.execute(text("SELECT trace_id, skus_json FROM recommendation_decision WHERE trace_id='T1'")).fetchone()
    assert row and row[0] == "T1" and "A" in row[1]


def test_market_intel_annotates_when_enabled(aligned_engine, monkeypatch):
    monkeypatch.setattr("src.app.services.market_intelligence_agent.gather_market_context",
                        lambda *a, **k: {"hippograph_insights": [{"id": "A", "kind": "product"}],
                                         "market_findings": [], "needs_market_evidence": False, "evidence_kinds": []})
    st = _state(flags={"ATTRIBUTION_ENABLED": False, "HIPPOGRAPH_FEEDBACK_ENABLED": True})
    mem = _FakeMem()
    run_intelligence_stage(st, mem=mem)
    assert st.payload.get("hippograph_insights") == [{"id": "A", "kind": "product"}]
    assert st.kv.get("hippograph_insights")  # flowed into the turn's kv (→ NQEInput)
    assert mem.store["u1"]["hippograph_insights"]  # persisted for next turn


def test_market_intel_shadow_observes_without_mutating(aligned_engine, monkeypatch):
    # A7: SHADOW mode COMPUTES + LOGS the market signals (observability) but does NOT mutate the
    # buyer-facing response/kv/memory — the governed first rung before trusting signals in a decision.
    monkeypatch.setattr("src.app.services.market_intelligence_agent.gather_market_context",
                        lambda *a, **k: {"hippograph_insights": [{"id": "A", "kind": "product", "label": "demand_peak"}],
                                         "market_findings": [{"x": 1}], "needs_market_evidence": False})
    traced = []
    monkeypatch.setattr("src.app.services.recommend_intelligence_stage.log_trace_event",
                        lambda **kw: traced.append(kw))
    st = _state(flags={"ATTRIBUTION_ENABLED": False, "HIPPOGRAPH_FEEDBACK_ENABLED": "shadow"})
    mem = _FakeMem()
    run_intelligence_stage(st, mem=mem)
    # NOT decision-affecting
    assert "hippograph_insights" not in st.payload and "market_findings" not in st.payload
    assert "hippograph_insights" not in (st.kv or {})
    assert "u1" not in mem.store
    # but the signals ARE observed in the trace (mode=shadow, applied=False)
    mi = [t for t in traced if t.get("event_type") == "market_intelligence"]
    assert mi and mi[0]["payload"]["mode"] == "shadow" and mi[0]["payload"]["applied"] is False
    assert mi[0]["payload"]["insights"] == 1 and "demand_peak" in mi[0]["payload"]["signal_labels"]


def test_market_projection_emits_scoped_non_sensitive_evidence(aligned_engine, monkeypatch):
    monkeypatch.setattr(
        "src.app.services.market_projection.projections",
        lambda *a, **k: {
            "A": {
                "units_per_day": 2.5, "dsi_days": 12, "stock_on_hand": 30,
                "dead_stock": False, "stockout": False, "bulk_frequency": {
                    "bulk_order_count": 2, "orders_per_30d": 0.667,
                }, "confidence": "seeded_demo", "as_of": "2026-07-24T00:00:00+00:00",
            },
        })
    traced = []
    monkeypatch.setattr(
        "src.app.services.recommend_intelligence_stage.log_trace_event",
        lambda **kw: traced.append(kw))
    st = _state(flags={"ATTRIBUTION_ENABLED": False})
    run_intelligence_stage(st, mem=_FakeMem())
    projection = [t for t in traced if t.get("event_type") == "market_projection"]
    assert projection and projection[0]["target_id"] == "A"
    assert projection[0]["source_type"] == "stage"
    assert projection[0]["payload"]["forecast_units_30d"] == 75
    assert projection[0]["payload"]["economics_included"] is False
    assert "wholesale_cents" not in projection[0]["payload"]


def test_stage_never_raises_on_bad_state(aligned_engine):
    st = _state(results=None, flags={"ATTRIBUTION_ENABLED": True, "HIPPOGRAPH_FEEDBACK_ENABLED": True})
    # should not raise even with results=None
    run_intelligence_stage(st, mem=_FakeMem())
