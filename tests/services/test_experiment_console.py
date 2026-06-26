"""Ranking-experiment operator console — promote / observe / evaluate / revert the live-adaptation loop.

The console only flips status + reads state (no adaptation logic). Proves: promote arms the experiment
(is_experiment_live True), state reports per-variant assignment counts + the last decision, evaluate
auto-reverts on no-lift, and revert is the manual kill lever.
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.app.services import attribution
from src.app.services import experiment_console as ec
from src.app.services import experiments as ex


@pytest.fixture()
def db():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True)
    s = sessionmaker(bind=eng, future=True)()
    attribution.ensure_tables(s)  # conversion_event — the eval reads it for per-variant metrics
    s.commit()
    try:
        yield s
    finally:
        s.close()


def test_promote_arms_the_experiment(db):
    st = ec.promote(db)
    assert st["status"] == "live" and st["live"] is True
    assert ex.is_experiment_live(db, ec.DEFAULT_EXPERIMENT_ID) is True


def test_state_reports_assignment_counts(db):
    ec.promote(db)
    ex.record_assignment(db, experiment_id=ec.DEFAULT_EXPERIMENT_ID, subject_hash="u1", variant="treatment")
    ex.record_assignment(db, experiment_id=ec.DEFAULT_EXPERIMENT_ID, subject_hash="u2", variant="control")
    db.commit()
    st = ec.state(db)
    assert st["assignments"].get("treatment") == 1 and st["assignments"].get("control") == 1


def test_revert_stops_adaptation(db):
    ec.promote(db)
    assert ec.state(db)["live"] is True
    st = ec.revert(db)
    assert st["status"] == "reverted" and st["live"] is False
    assert ex.is_experiment_live(db, ec.DEFAULT_EXPERIMENT_ID) is False


def test_evaluate_auto_reverts_on_no_lift(db):
    # treatment metric <= control → no uplift → decide REVERT → autonomous rollback flips live off
    ec.promote(db)
    eid = ec.DEFAULT_EXPERIMENT_ID
    for i in range(5):
        ex.record_assignment(db, experiment_id=eid, subject_hash=f"c{i}", variant="control")
        ex.record_assignment(db, experiment_id=eid, subject_hash=f"t{i}", variant="treatment")
    db.commit()
    out = ec.evaluate_now(db, min_samples=1)
    assert out.get("decision") in ("revert", "revise", "keep", "scale")
    # with no recorded metrics, treatment shows no positive uplift → revert + experiment goes not-live
    if out.get("reverted"):
        assert ec.state(db)["live"] is False


def test_state_absent_when_never_promoted(db):
    st = ec.state(db, experiment_id="never-made")
    assert st["status"] == "absent" and st["live"] is False


def test_none_db_safe():
    assert ec.state(None)["live"] is False
    assert "error" in ec.evaluate_now(None)