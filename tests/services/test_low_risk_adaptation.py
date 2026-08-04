"""S7 low-risk adaptation — small canary, treatment caps, kill switch, claim-safe template phrasing."""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.app.services import experiment_ops as ops
from src.app.services import template_phrasing as tp
from src.app.services import experiments as ex
from tests.experiment_helpers import apply_experiment_migrations, create_sealed_experiment
from src.app.services.ranking_nudge import apply_experiment_nudge


@pytest.fixture()
def db():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True)
    s = sessionmaker(bind=eng, future=True)()
    apply_experiment_migrations(s)
    try:
        yield s
    finally:
        s.close()


# ── canary exposure ───────────────────────────────────────────────────────────
def test_canary_fraction_limits_treatment_exposure():
    n = 4000
    treated = sum(1 for i in range(n)
                  if ops.canary_assignment(experiment_id="e1", subject=f"u{i}", canary_fraction=0.1) == "treatment")
    # only ~ fraction×0.5 of subjects get treatment — a SMALL canary, not half the traffic
    assert 0.02 * n < treated < 0.08 * n


def test_canary_is_deterministic_per_subject():
    a = ops.canary_assignment(experiment_id="e1", subject="u42", canary_fraction=0.5)
    b = ops.canary_assignment(experiment_id="e1", subject="u42", canary_fraction=0.5)
    assert a == b  # stable experience across turns


def test_zero_fraction_means_no_treatment():
    assert all(ops.canary_assignment(experiment_id="e", subject=f"u{i}", canary_fraction=0.0) == "control"
               for i in range(50))


# ── kill switch ───────────────────────────────────────────────────────────────
def test_global_kill_switch(monkeypatch):
    monkeypatch.delenv("ADAPTATION_KILL_SWITCH", raising=False)
    assert ops.adaptation_killed() is False
    monkeypatch.setenv("ADAPTATION_KILL_SWITCH", "1")
    assert ops.adaptation_killed() is True


# ── treatment caps on the nudge ───────────────────────────────────────────────
def _rows(*skus):
    return [{"sku": s, "score": 1.0} for s in skus]


def test_max_nudged_items_caps_the_blast_radius():
    rows = _rows("A", "B", "C", "D", "E")
    out = apply_experiment_nudge(rows, recall_ids=["A", "B", "C", "D", "E"], assignment="treatment",
                                 live=True, max_boost=0.05, max_nudged_items=2)
    nudged = [r for r in out if r.get("_nudge_delta")]
    assert len(nudged) == 2  # only 2 boosted despite 5 recalled — cap holds


def test_control_and_non_live_are_identity():
    rows = _rows("A", "B")
    assert apply_experiment_nudge(rows, recall_ids=["A"], assignment="control", live=True) is rows
    assert apply_experiment_nudge(rows, recall_ids=["A"], assignment="treatment", live=False) is rows


# ── template phrasing: tone-only, claim-safe ─────────────────────────────────
def test_phrasing_changes_tone_not_facts():
    msg = "I found 3 laptops between $800 and $1800."
    out, applied = tp.choose_and_apply(msg, variant="treatment")
    assert applied == "treatment" and out.startswith("Happy to help!")
    # claim content (the numbers) is preserved exactly
    import re
    assert re.findall(r"\d", msg) == re.findall(r"\d", out)


def test_phrasing_control_is_identity():
    msg = "Here are some options."
    assert tp.choose_and_apply(msg, variant="control") == (msg, "control")


def test_phrasing_claim_guard_reverts_if_numbers_change(monkeypatch):
    # inject a malicious style that adds a fake spec — the guard must discard it
    monkeypatch.setitem(tp._STYLES, "treatment", lambda m: m + " (only 2 left!)")
    out, applied = tp.choose_and_apply("We have stock.", variant="treatment")
    assert applied == "control" and out == "We have stock."  # number-changing variant rejected


def test_apply_phrasing_respects_kill_switch(db, monkeypatch):
    monkeypatch.setenv("ADAPTATION_KILL_SWITCH", "1")
    create_sealed_experiment(
        db, name="template_phrasing_v1", target_metric="csat"
    )
    out, info = tp.apply_phrasing_experiment(db, "I found 3 options.", subject="u1",
                                             flags={"TEMPLATE_PHRASING_CANARY_FRACTION": 1.0})
    assert out == "I found 3 options." and info["killed"] is True  # killed → control text


def test_apply_phrasing_not_live_is_control(db):
    out, info = tp.apply_phrasing_experiment(db, "Hello.", subject="u1")
    assert out == "Hello." and info["live"] is False
