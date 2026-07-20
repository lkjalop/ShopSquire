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
    """n subjects per arm; each control subject converts at control_value$, treatment at treatment_value$.
    Assignment is stamped BEFORE the conversion (2026-06-24 < 2026-06-25) so the post-assignment
    attribution window credits the conversion to the experiment."""
    for arm, val in (("control", control_value), ("treatment", treatment_value)):
        for i in range(n):
            subj = f"{eid}-{arm}-{i}"  # namespaced per experiment so subjects/conversions don't collide
            ex.record_assignment(db, experiment_id=eid, subject_hash=subj, variant=arm, assigned_at="2026-06-24")
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


def test_pre_assignment_conversions_are_not_credited(db):
    """A conversion that happened BEFORE the subject was assigned must NOT count toward uplift —
    otherwise pre-existing buyers inflate whichever arm they land in."""
    eid = ex.create_experiment(db, name="causal", target_metric="rpv", status="live")
    # treatment subjects each have a BIG conversion that PREDATES assignment (should be excluded),
    # plus a small valid one after; control has a valid one after. Without the window the treatment
    # would look like a huge winner purely from pre-existing revenue.
    for arm in ("control", "treatment"):
        for i in range(6):
            subj = f"{eid}-{arm}-{i}"
            ex.record_assignment(db, experiment_id=eid, subject_hash=subj, variant=arm, assigned_at="2026-06-10")
            db.execute(text("INSERT INTO conversion_event (id,decision_id,order_id,uid_hash,"
                            "attributed_skus_json,value_cents,converted_at) VALUES (:id,'d',:o,:u,'[]',:v,:t)"),
                       {"id": f"{subj}-after", "o": f"order-{subj}-after",
                        "u": subj, "v": 10000, "t": "2026-06-12"})  # valid (after)
            if arm == "treatment":
                db.execute(text("INSERT INTO conversion_event (id,decision_id,order_id,uid_hash,"
                                "attributed_skus_json,value_cents,converted_at) VALUES (:id,'d',:o,:u,'[]',:v,:t)"),
                           {"id": f"{subj}-before", "o": f"order-{subj}-before",
                            "u": subj, "v": 999999, "t": "2026-06-01"})  # PRE-assignment
    db.commit()
    out = evaluate_experiment(db, eid, min_samples=2)
    # both arms have equal POST-assignment revenue → ~0% uplift (the pre-assignment windfall is excluded)
    assert abs(out["uplift_pct"]) < 1.0, f"pre-assignment revenue leaked into uplift: {out['uplift_pct']}"


def test_returns_guardrail_reverts_revenue_win_with_higher_returns(db):
    from src.app.services.experiment_eval import returns_guardrail
    db.execute(text("CREATE TABLE orders (id TEXT, customer_id TEXT, total_cents INTEGER, status TEXT, "
                    "created_at TEXT, updated_at TEXT)"))
    eid = ex.create_experiment(db, name="returns-x", target_metric="rpv", status="live")
    # treatment earns MORE revenue but its orders get refunded more often → trust/margin damage
    for arm, val, refund_every in (("control", 100.0, 5), ("treatment", 140.0, 2)):
        for i in range(8):
            subj = f"{eid}-{arm}-{i}"
            oid = f"O-{subj}"
            ex.record_assignment(db, experiment_id=eid, subject_hash=subj, variant=arm, assigned_at="2026-06-24")
            status = "refunded" if (i % refund_every == 0) else "paid"
            db.execute(text("INSERT INTO orders (id, status) VALUES (:o,:s)"), {"o": oid, "s": status})
            db.execute(text("INSERT INTO conversion_event (id, decision_id, order_id, uid_hash, "
                            "attributed_skus_json, value_cents, converted_at) VALUES (:id,:d,:o,:u,'[]',:v,'2026-06-25')"),
                       {"id": f"{subj}-c", "d": f"D{subj}", "o": oid, "u": subj, "v": int(val * 100)})
    db.commit()
    g = returns_guardrail(db, eid)
    assert g.get("returns", 0) < 0  # treatment returns higher → negative guardrail delta
    out = evaluate_experiment(db, eid, min_samples=2, guardrail_fn=returns_guardrail)
    assert out["uplift_pct"] > 0  # revenue went UP ...
    assert out["decision"] == "revert" and out["reason"] == "guardrail_breach"  # ... but returns reverts it
    assert ex.is_experiment_live(db, eid) is False


def test_from_return_adapter_maps_envelope():
    from src.app.services.market_signal_adapters import from_return
    sig = from_return({"id": "O1", "status": "refunded", "updated_at": "2026-06-25"})
    assert sig and sig.signal_type == "return" and sig.payload["order_id"] == "O1"
    assert from_return({"status": "refunded"}) is None  # no order id → skip


def test_eval_task_registered_and_default_off():
    from src.app.workers.celery_app import celery_app
    from src.app.tasks.experiment_tasks import evaluate_experiments, _enabled
    assert "src.app.tasks.experiment_tasks" in (celery_app.conf.imports or ())
    assert _enabled() is False
    assert evaluate_experiments.run() == {"skipped": "disabled"}
