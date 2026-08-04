"""S6 experiment operationalization — broader guardrails, worker health, stale detect, rollback drill.

Builds on the existing assignment/uplift/rollback; these tests prove the OPERATIONAL safety net:
multi-dimensional guardrails, a fail-safe when the safety loop stops, zombie cleanup, and a DR drill
that verifies the kill switch actually disables the adaptation.
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.app.services import experiments as ex
from src.app.services import experiment_ops as ops
from tests.experiment_helpers import apply_experiment_migrations

TENANT = "tenant-a"


def _experiment(db, name: str, status: str = "live"):
    return ex.create_experiment(
        db, tenant_id=TENANT, name=name, target_metric="rpv", status=status,
        baseline={"variant": "control"}, eligibility={"all": True},
        min_samples=2, min_window_seconds=60, rollback_threshold_pct=2.0,
        guardrails={}, terminal_policy={"allowed": ["keep", "scale", "revise", "revert"]},
    )


@pytest.fixture()
def db():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True)
    s = sessionmaker(bind=eng, future=True)()
    apply_experiment_migrations(s)
    try:
        yield s
    finally:
        s.close()


# ── broader guardrails ────────────────────────────────────────────────────────
def test_composite_merges_guardrails():
    g = ops.composite_guardrail(lambda d, e: {"returns": -1.0}, lambda d, e: {"margin": 2.0})
    assert g(None, "x", tenant_id=TENANT) == {"returns": -1.0, "margin": 2.0}


def test_composite_isolates_a_throwing_guardrail():
    def boom(d, e):
        raise RuntimeError("nope")
    g = ops.composite_guardrail(boom, lambda d, e: {"returns": -3.0})
    assert g(None, "x", tenant_id=TENANT) == {"returns": -3.0}


def test_escalation_rate_guardrail_breaches_when_treatment_escalates_more(db):
    from src.app.services import human_feedback as hf
    eid = _experiment(db, "esc")
    for arm, escalate in (("control", False), ("treatment", True)):
        for i in range(6):
            subj = f"{eid}-{arm}-{i}"
            ex.record_assignment(
                db, tenant_id=TENANT, experiment_id=eid, subject_hash=subj, variant=arm
            )
            if escalate:  # every treatment subject escalates → treatment rate >> control rate
                hf.record_feedback(
                    db, "escalation", subject_hash=subj,
                    entity_ref="SKU-1", tenant_id=TENANT,
                )
    db.commit()
    out = ops.escalation_rate_guardrail(db, eid, tenant_id=TENANT)
    assert out["escalation_rate"] < 0  # treatment escalates more → negative → breach


# ── worker health (heartbeat) ─────────────────────────────────────────────────
def test_heartbeat_staleness(db):
    ops.record_heartbeat(db, now_iso="2026-06-25 10:00:00")
    assert ops.eval_is_stale(db, max_age_seconds=3600, now_iso="2026-06-25 10:30:00") is False
    assert ops.eval_is_stale(db, max_age_seconds=3600, now_iso="2026-06-25 12:00:00") is True
    # a loop that has never beaten → stale (unknown liveness is unsafe)
    assert ops.eval_is_stale(db, max_age_seconds=1, name="never_beaten") is True


def test_pause_live_when_eval_stale_is_failsafe(db):
    live = _experiment(db, "canary")
    ops.record_heartbeat(db, now_iso="2026-06-25 08:00:00")  # last beat 4h ago
    res = ops.pause_live_if_eval_stale(
        db, tenant_id=TENANT, max_age_seconds=3600, now_iso="2026-06-25 12:00:00"
    )
    assert res["stale"] is True and live in res["paused"]
    assert ex.is_experiment_live(db, live, tenant_id=TENANT) is False


def test_no_pause_when_eval_fresh(db):
    live = _experiment(db, "ok")
    ops.record_heartbeat(db, now_iso="2026-06-25 11:55:00")
    res = ops.pause_live_if_eval_stale(
        db, tenant_id=TENANT, max_age_seconds=3600, now_iso="2026-06-25 12:00:00"
    )
    assert res["stale"] is False and res["paused"] == []
    assert ex.is_experiment_live(db, live, tenant_id=TENANT) is True


# ── stale-experiment detection ────────────────────────────────────────────────
def test_detect_and_revert_zombie_experiments(db):
    eid = _experiment(db, "zombie")
    # ACTIVATED long ago (started_at), so it's a genuine zombie
    db.execute(text("UPDATE experiment_run SET started_at='2026-06-01 00:00:00' WHERE id=:i"), {"i": eid})
    db.commit()
    stale = ops.detect_stale_experiments(
        db, tenant_id=TENANT, max_age_seconds=86400, now_iso="2026-06-25 00:00:00"
    )
    assert any(s["experiment_id"] == eid for s in stale)
    reverted = ops.auto_revert_stale(
        db, tenant_id=TENANT, max_age_seconds=86400, now_iso="2026-06-25 00:00:00"
    )
    assert eid in reverted and ex.is_experiment_live(db, eid, tenant_id=TENANT) is False


def test_old_draft_activated_today_is_not_stale(db):
    """Finding 5: age is measured from ACTIVATION, not creation — an old draft flipped live today must
    NOT be classified stale immediately."""
    eid = _experiment(db, "reborn", status="draft")
    db.execute(text("UPDATE experiment_run SET created_at='2026-01-01 00:00:00' WHERE id=:i"), {"i": eid})
    db.commit()
    ex.set_status(db, tenant_id=TENANT, experiment_id=eid, status="live")
    db.execute(text("UPDATE experiment_run SET started_at='2026-06-25 09:00:00' WHERE id=:i"), {"i": eid})
    db.commit()
    stale = ops.detect_stale_experiments(
        db, tenant_id=TENANT, max_age_seconds=86400, now_iso="2026-06-25 10:00:00"
    )
    assert all(s["experiment_id"] != eid for s in stale)  # 1h since activation → fresh


# ── forced rollback drill ─────────────────────────────────────────────────────
def test_forced_rollback_drill_verifies_kill_switch(db):
    a = _experiment(db, "a")
    b = _experiment(db, "b")
    report = ops.forced_rollback_drill(db, tenant_id=TENANT)
    assert set(report["reverted"]) == {a, b}
    assert report["verified_not_live"] is True and report["failures"] == []
    assert ex.is_experiment_live(db, a, tenant_id=TENANT) is False
    assert ex.is_experiment_live(db, b, tenant_id=TENANT) is False


def test_drill_safe_without_db():
    assert ops.forced_rollback_drill(None, tenant_id=TENANT)["verified_not_live"] is True


def test_watchdog_task_registered_and_default_off():
    from src.app.workers.celery_app import celery_app
    from src.app.tasks.experiment_ops_tasks import experiment_watchdog, _enabled
    assert "src.app.tasks.experiment_ops_tasks" in (celery_app.conf.imports or ())
    assert _enabled() is False
    assert experiment_watchdog.run() == {"skipped": "disabled"}
