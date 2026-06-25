"""Experiment evaluation runtime — the autonomous rollback loop (services/experiment_eval.py)."""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.app.services import experiments as ex
from src.app.services.experiment_eval import evaluate_experiment, evaluate_live_experiments


@pytest.fixture()
def db():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True)
    s = sessionmaker(bind=eng, future=True)()
    ex.ensure_tables(s)
    from src.app.services import attribution
    attribution.ensure_tables(s)
    try:
        yield s
    finally:
        s.close()


def _seed(db, eid, *, control_value, treatment_value, n=8):
    """n subjects per arm; each control subject converts at control_value$, treatment at treatment_value$."""
    for arm, val in (("control", control_value), ("treatment", treatment_value)):
        for i in range(n):
            subj = f"{eid}-{arm}-{i}"  # namespaced per experiment so subjects/conversions don't collide
            ex.record_assignment(db, experiment_id=eid, subject_hash=subj, variant=arm)
            if val > 0:
                db.execute(text("INSERT INTO conversion_event (id, decision_id, order_id, uid_hash, "
                                "attributed_skus_json, value_cents, converted_at) "
                                "VALUES (:id,:d,:o,:u,'[]',:v,'2026-06-25')"),
                           {"id": f"{subj}-c", "d": f"D{subj}", "o": f"O{subj}", "u": subj, "v": int(val * 100)})
    db.commit()


def test_winning_treatment_keeps_or_scales(db):
    eid = ex.create_experiment(db, name="win", target_metric="rpv", status="live")
    _seed(db, eid, control_value=100.0, treatment_value=130.0, n=8)  # +30% revenue/subject
    out = evaluate_experiment(db, eid, min_samples=2)
    assert out["uplift_pct"] == pytest.approx(30.0, abs=1.0)
    assert out["decision"] in ("keep", "scale")
    assert "reverted" not in out
    assert ex.is_experiment_live(db, eid) is True  # still live


def test_losing_treatment_auto_reverts(db):
    eid = ex.create_experiment(db, name="lose", target_metric="rpv", status="live")
    _seed(db, eid, control_value=130.0, treatment_value=100.0, n=8)  # treatment is significantly WORSE
    out = evaluate_experiment(db, eid, min_samples=2)
    assert out["uplift_pct"] < 0
    assert out["decision"] == "revert" and out.get("reverted") is True
    assert ex.is_experiment_live(db, eid) is False  # AUTONOMOUS ROLLBACK — nudge stops


def test_inconclusive_treatment_revises_not_reverts(db):
    eid = ex.create_experiment(db, name="flat", target_metric="rpv", status="live")
    _seed(db, eid, control_value=100.0, treatment_value=100.0, n=8)  # no difference → inconclusive
    out = evaluate_experiment(db, eid, min_samples=2)
    assert out["decision"] == "revise" and "reverted" not in out
    assert ex.is_experiment_live(db, eid) is True  # not enough evidence to revert — keep measuring


def test_guardrail_breach_auto_reverts_despite_win(db):
    eid = ex.create_experiment(db, name="goodhart", target_metric="rpv", status="live")
    _seed(db, eid, control_value=100.0, treatment_value=140.0, n=8)  # target +40% ...
    out = evaluate_experiment(db, eid, min_samples=2, guardrail_fn=lambda _db, _e: {"margin": -5.0})  # ...but margin -5%
    assert out["decision"] == "revert" and out["reason"] == "guardrail_breach"
    assert ex.is_experiment_live(db, eid) is False


def test_evaluate_live_only(db):
    live = ex.create_experiment(db, name="live-x", target_metric="rpv", status="live")
    draft = ex.create_experiment(db, name="draft-x", target_metric="rpv", status="draft")
    _seed(db, live, control_value=100.0, treatment_value=100.0, n=4)
    _seed(db, draft, control_value=100.0, treatment_value=300.0, n=4)
    outs = evaluate_live_experiments(db, min_samples=2)
    ids = {o["experiment_id"] for o in outs}
    assert live in ids and draft not in ids  # only the live one is evaluated


def test_none_db_safe():
    assert evaluate_live_experiments(None) == []


def test_eval_task_registered_and_default_off():
    from src.app.workers.celery_app import celery_app
    from src.app.tasks.experiment_tasks import evaluate_experiments, _enabled
    assert "src.app.tasks.experiment_tasks" in (celery_app.conf.imports or ())
    assert _enabled() is False
    assert evaluate_experiments.run() == {"skipped": "disabled"}
