"""decision_outcome + attribution_event store (Module 2/6 close-the-loop) — schema drift, record API,
and the experiment_console.evaluate wiring that persists each terminal outcome."""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.app.services import market_outcome as mo


@pytest.fixture()
def db():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True)
    s = sessionmaker(bind=eng, future=True)()
    try:
        yield s
    finally:
        s.close()


_OUTCOME_COLS = {"id", "tenant_id", "decision_ref", "source", "target_metric", "uplift_pct", "decision",
                 "significant", "n_control", "n_treatment", "reverted", "window", "recorded_at"}
_ATTR_COLS = {"id", "tenant_id", "decision_ref", "metric", "value", "segment", "occurred_at", "recorded_at"}


def test_ensure_tables_schema_drift(db):
    mo.ensure_tables(db)
    oc = {r[1] for r in db.execute(text("PRAGMA table_info(decision_outcome)")).fetchall()}
    ac = {r[1] for r in db.execute(text("PRAGMA table_info(attribution_event)")).fetchall()}
    assert oc == _OUTCOME_COLS, f"decision_outcome drift: {oc ^ _OUTCOME_COLS}"
    assert ac == _ATTR_COLS, f"attribution_event drift: {ac ^ _ATTR_COLS}"
    mo.ensure_tables(db)  # idempotent — second call must not raise


def test_record_outcome_and_load(db):
    oid = mo.record_outcome(db, decision_ref="ranking_nudge_v1", decision="keep", uplift_pct=4.2,
                            significant=True, n_control=120, n_treatment=118, reverted=False)
    assert oid
    rows = mo.load_recent_outcomes(db, decision_ref="ranking_nudge_v1")
    assert len(rows) == 1
    r = rows[0]
    assert r["decision"] == "keep" and r["uplift_pct"] == 4.2 and r["significant"] is True
    assert r["n_control"] == 120 and r["reverted"] is False


def test_record_outcome_is_append_only_history(db):
    mo.record_outcome(db, decision_ref="exp-1", decision="keep", uplift_pct=2.0)
    mo.record_outcome(db, decision_ref="exp-1", decision="revert", uplift_pct=-3.0, reverted=True)
    rows = mo.load_recent_outcomes(db, decision_ref="exp-1")
    assert len(rows) == 2  # both kept — an outcome history, not a single mutable row


def test_record_attribution(db):
    aid = mo.record_attribution(db, decision_ref="exp-1", metric="conversion", value=0.21, segment="smb")
    assert aid
    n = db.execute(text("SELECT COUNT(*) FROM attribution_event WHERE decision_ref='exp-1'")).scalar()
    assert n == 1


def test_record_outcome_rejects_blank_ref(db):
    assert mo.record_outcome(db, decision_ref="", decision="keep") is None


def test_evaluate_now_records_an_outcome(db, monkeypatch):
    # the wiring: experiment_console.evaluate_now must persist a decision_outcome from the eval result.
    import src.app.services.experiment_console as ec
    monkeypatch.setattr(
        "src.app.services.experiment_eval.evaluate_experiment",
        lambda _db, eid, min_samples=30: {"decision": "keep", "uplift_pct": 5.5, "significant": True,
                                          "n_control": 50, "n_treatment": 50},
    )
    out = ec.evaluate_now(db, experiment_id="ranking_nudge_v1", min_samples=10)
    assert out.get("decision") == "keep"
    rows = mo.load_recent_outcomes(db, decision_ref="ranking_nudge_v1")
    assert len(rows) == 1 and rows[0]["decision"] == "keep" and rows[0]["uplift_pct"] == 5.5
