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


def test_stage_never_raises_on_bad_state(aligned_engine):
    st = _state(results=None, flags={"ATTRIBUTION_ENABLED": True, "HIPPOGRAPH_FEEDBACK_ENABLED": True})
    # should not raise even with results=None
    run_intelligence_stage(st, mem=_FakeMem())
