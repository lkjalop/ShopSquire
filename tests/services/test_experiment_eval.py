"""Experiment evaluation runtime — the autonomous rollback loop (services/experiment_eval.py)."""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.app.services import experiments as ex
from src.app.services.experiment_eval import evaluate_experiment, evaluate_live_experiments
from tests.experiment_helpers import apply_experiment_migrations

TENANT = "tenant-a"


def _experiment(db, *, name: str, status: str = "live", tenant_id: str = TENANT):
    return ex.create_experiment(
        db, tenant_id=tenant_id, name=name, target_metric="rpv", status=status,
        baseline={"variant": "control"}, eligibility={"all": True},
        min_samples=2, min_window_seconds=60, rollback_threshold_pct=2.0,
        guardrails={"returns": {"max_degradation_pct": 2.0}},
        terminal_policy={"allowed": ["keep", "scale", "revise", "revert"]},
    )


@pytest.fixture()
def db():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True)
    s = sessionmaker(bind=eng, future=True)()
    apply_experiment_migrations(s)
    from src.app.services import attribution
    attribution.ensure_tables(s)
    try:
        yield s
    finally:
        s.close()


def _seed(db, eid, *, control_value, treatment_value, n=8, tenant_id=TENANT):
    """n subjects per arm; each control subject converts at control_value$, treatment at treatment_value$.
    Assignment is stamped BEFORE the conversion (2026-06-24 < 2026-06-25) so the post-assignment
    attribution window credits the conversion to the experiment."""
    for arm, val in (("control", control_value), ("treatment", treatment_value)):
        for i in range(n):
            subj = f"{eid}-{arm}-{i}"  # namespaced per experiment so subjects/conversions don't collide
            ex.record_assignment(
                db, tenant_id=tenant_id, experiment_id=eid, subject_hash=subj,
                variant=arm, assigned_at="2026-06-24",
            )
            if val > 0:
                db.execute(text("INSERT INTO conversion_event (id, decision_id, order_id, uid_hash, "
                                "attributed_skus_json, value_cents, converted_at, tenant_id) "
                                "VALUES (:id,:d,:o,:u,'[]',:v,'2026-06-25',:t)"),
                           {"id": f"{subj}-c", "d": f"D{subj}", "o": f"O{subj}",
                            "u": subj, "v": int(val * 100), "t": tenant_id})
    db.execute(text(
        "UPDATE experiment_run SET started_at='2026-06-24 00:00:00' "
        "WHERE id=:e AND tenant_id=:t"
    ), {"e": eid, "t": tenant_id})
    db.commit()


def test_winning_treatment_keeps_or_scales(db):
    eid = _experiment(db, name="win")
    _seed(db, eid, control_value=100.0, treatment_value=130.0, n=8)  # +30% revenue/subject
    out = evaluate_experiment(db, eid, tenant_id=TENANT)
    assert out["uplift_pct"] == pytest.approx(30.0, abs=1.0)
    assert out["decision"] in ("keep", "scale")
    assert "reverted" not in out
    assert ex.is_experiment_live(db, eid, tenant_id=TENANT) is True  # still live


def test_losing_treatment_auto_reverts(db):
    eid = _experiment(db, name="lose")
    _seed(db, eid, control_value=130.0, treatment_value=100.0, n=8)  # treatment is significantly WORSE
    out = evaluate_experiment(db, eid, tenant_id=TENANT)
    assert out["uplift_pct"] < 0
    assert out["decision"] == "revert" and out.get("reverted") is True
    assert ex.is_experiment_live(db, eid, tenant_id=TENANT) is False


def test_inconclusive_treatment_revises_not_reverts(db):
    eid = _experiment(db, name="flat")
    _seed(db, eid, control_value=100.0, treatment_value=100.0, n=8)  # no difference → inconclusive
    out = evaluate_experiment(db, eid, tenant_id=TENANT)
    assert out["decision"] == "revise" and "reverted" not in out
    assert ex.is_experiment_live(db, eid, tenant_id=TENANT) is True


def test_guardrail_breach_auto_reverts_despite_win(db):
    eid = _experiment(db, name="goodhart")
    _seed(db, eid, control_value=100.0, treatment_value=140.0, n=8)  # target +40% ...
    out = evaluate_experiment(
        db, eid, tenant_id=TENANT, guardrail_fn=lambda _db, _e: {"margin": -5.0}
    )
    assert out["decision"] == "revert" and out["reason"] == "guardrail_breach"
    assert ex.is_experiment_live(db, eid, tenant_id=TENANT) is False


def test_evaluate_live_only(db):
    live = _experiment(db, name="live-x")
    draft = _experiment(db, name="draft-x", status="draft")
    _seed(db, live, control_value=100.0, treatment_value=100.0, n=4)
    _seed(db, draft, control_value=100.0, treatment_value=300.0, n=4)
    outs = evaluate_live_experiments(db, tenant_id=TENANT)
    ids = {o["experiment_id"] for o in outs}
    assert live in ids and draft not in ids  # only the live one is evaluated


def test_none_db_safe():
    assert evaluate_live_experiments(None, tenant_id=TENANT) == []


def test_pre_assignment_conversions_are_not_credited(db):
    """A conversion that happened BEFORE the subject was assigned must NOT count toward uplift —
    otherwise pre-existing buyers inflate whichever arm they land in."""
    eid = _experiment(db, name="causal")
    # treatment subjects each have a BIG conversion that PREDATES assignment (should be excluded),
    # plus a small valid one after; control has a valid one after. Without the window the treatment
    # would look like a huge winner purely from pre-existing revenue.
    for arm in ("control", "treatment"):
        for i in range(6):
            subj = f"{eid}-{arm}-{i}"
            ex.record_assignment(
                db, tenant_id=TENANT, experiment_id=eid, subject_hash=subj,
                variant=arm, assigned_at="2026-06-10",
            )
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
    db.execute(text("UPDATE experiment_run SET started_at='2026-06-10' WHERE id=:e"), {"e": eid})
    out = evaluate_experiment(db, eid, tenant_id=TENANT)
    # both arms have equal POST-assignment revenue → ~0% uplift (the pre-assignment windfall is excluded)
    assert abs(out["uplift_pct"]) < 1.0, f"pre-assignment revenue leaked into uplift: {out['uplift_pct']}"


def test_returns_guardrail_reverts_revenue_win_with_higher_returns(db):
    from src.app.services.experiment_eval import returns_guardrail
    db.execute(text("CREATE TABLE orders (id TEXT, customer_id TEXT, total_cents INTEGER, status TEXT, "
                    "created_at TEXT, updated_at TEXT)"))
    eid = _experiment(db, name="returns-x")
    # treatment earns MORE revenue but its orders get refunded more often → trust/margin damage
    for arm, val, refund_every in (("control", 100.0, 5), ("treatment", 140.0, 2)):
        for i in range(8):
            subj = f"{eid}-{arm}-{i}"
            oid = f"O-{subj}"
            ex.record_assignment(
                db, tenant_id=TENANT, experiment_id=eid, subject_hash=subj,
                variant=arm, assigned_at="2026-06-24",
            )
            status = "refunded" if (i % refund_every == 0) else "paid"
            db.execute(text("INSERT INTO orders (id, status) VALUES (:o,:s)"), {"o": oid, "s": status})
            db.execute(text("INSERT INTO conversion_event (id, decision_id, order_id, uid_hash, "
                            "attributed_skus_json, value_cents, converted_at, tenant_id) "
                            "VALUES (:id,:d,:o,:u,'[]',:v,'2026-06-25',:t)"),
                       {"id": f"{subj}-c", "d": f"D{subj}", "o": oid,
                        "u": subj, "v": int(val * 100), "t": TENANT})
    db.commit()
    g = returns_guardrail(db, eid, tenant_id=TENANT)
    assert g.get("returns", 0) < 0  # treatment returns higher → negative guardrail delta
    db.execute(text("UPDATE experiment_run SET started_at='2026-06-24' WHERE id=:e"), {"e": eid})
    out = evaluate_experiment(db, eid, tenant_id=TENANT, guardrail_fn=returns_guardrail)
    assert out["uplift_pct"] > 0  # revenue went UP ...
    assert out["decision"] == "revert" and out["reason"] == "guardrail_breach"  # ... but returns reverts it
    assert ex.is_experiment_live(db, eid, tenant_id=TENANT) is False


def test_cross_tenant_and_late_outcomes_receive_no_credit(db):
    eid = _experiment(db, name="tenant-window")
    _seed(db, eid, control_value=100.0, treatment_value=130.0, n=4)
    treatment_subject = f"{eid}-treatment-0"
    db.execute(text(
        "INSERT INTO conversion_event "
        "(id, decision_id, order_id, uid_hash, attributed_skus_json, value_cents, converted_at, tenant_id) "
        "VALUES ('cross-tenant','d-cross','o-cross',:u,'[]',9999999,'2026-06-25','tenant-b')"
    ), {"u": treatment_subject})
    db.execute(text(
        "UPDATE experiment_run SET ended_at='2026-06-26 00:00:00' WHERE id=:e"
    ), {"e": eid})
    db.execute(text(
        "INSERT INTO conversion_event "
        "(id, decision_id, order_id, uid_hash, attributed_skus_json, value_cents, converted_at, tenant_id) "
        "VALUES ('late','d-late','o-late',:u,'[]',9999999,'2026-06-27',:t)"
    ), {"u": treatment_subject, "t": TENANT})
    db.commit()
    out = evaluate_experiment(db, eid, tenant_id=TENANT)
    assert out["uplift_pct"] == pytest.approx(30.0, abs=1.0)


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
