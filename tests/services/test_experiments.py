"""Unit tests for the experiment + rollback gate (services/experiments.py).

The two non-negotiables get explicit tests: anti-false-positive (a seasonal lift on BOTH arms is not
credited) and anti-Goodhart (a guardrail breach reverts even when the target improved).
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.app.services import experiments as ex
from src.app.services.experiments import (
    DECISION_KEEP,
    DECISION_REVERT,
    DECISION_REVISE,
    DECISION_SCALE,
    assign_variant,
    compute_uplift,
    decide,
    evaluate_experiment,
)


# ── assignment ────────────────────────────────────────────────────────────────
def test_assignment_deterministic_and_stable():
    a = assign_variant(experiment_id="E1", subject="user-1", variants=["control", "treatment"])
    b = assign_variant(experiment_id="E1", subject="user-1", variants=["control", "treatment"])
    assert a == b and a in ("control", "treatment")


def test_assignment_distributes_across_subjects():
    seen = {assign_variant(experiment_id="E1", subject=f"u{i}", variants=["control", "treatment"]) for i in range(200)}
    assert seen == {"control", "treatment"}  # both arms get used


def test_assignment_empty_variants_defaults_control():
    assert assign_variant(experiment_id="E", subject="s", variants=[]) == "control"


# ── uplift + anti-false-positive ──────────────────────────────────────────────
def test_uplift_positive_significant():
    up = compute_uplift([1.0] * 50, [1.2] * 50)
    assert up.uplift_pct == pytest.approx(20.0, abs=0.1) and up.significant is True


def test_uplift_insufficient_samples_not_significant():
    assert compute_uplift([1, 2, 3], [2, 3, 4]).significant is False


def test_anti_false_positive_seasonal_bump_not_credited():
    # a "season" lifts BOTH arms equally → the difference is ~0 → not a treatment win
    control = [10.0 + 5.0 for _ in range(60)]   # +5 seasonal
    treatment = [10.0 + 5.0 for _ in range(60)]  # same +5 seasonal, no real treatment effect
    up = compute_uplift(control, treatment)
    assert up.uplift_pct == pytest.approx(0.0, abs=0.1)
    out = decide(target_uplift_pct=up.uplift_pct, significant=up.significant)
    assert out["decision"] in (DECISION_REVISE, DECISION_REVERT)  # never keep/scale on a seasonal artifact


# ── terminal decision (anti-Goodhart) ─────────────────────────────────────────
def test_anti_goodhart_guardrail_breach_reverts_despite_target_win():
    out = decide(target_uplift_pct=15.0, significant=True, guardrail_deltas_pct={"margin": -3.0})
    assert out["decision"] == DECISION_REVERT and out["reason"] == "guardrail_breach"
    assert "margin" in out["breached"]


def test_scale_keep_revise_revert_paths():
    assert decide(target_uplift_pct=12.0, significant=True)["decision"] == DECISION_SCALE
    assert decide(target_uplift_pct=4.0, significant=True)["decision"] == DECISION_KEEP
    assert decide(target_uplift_pct=12.0, significant=False)["decision"] == DECISION_REVISE
    assert decide(target_uplift_pct=0.5, significant=True)["decision"] == DECISION_REVERT


def test_guardrail_within_threshold_does_not_revert():
    out = decide(target_uplift_pct=12.0, significant=True, guardrail_deltas_pct={"returns": -1.0},
                 rollback_threshold_pct=2.0)
    assert out["decision"] == DECISION_SCALE  # -1% < 2% threshold → not breached


def test_evaluate_experiment_one_shot():
    out = evaluate_experiment(control=[1.0] * 50, treatment=[1.15] * 50, guardrail_deltas_pct={"margin": 0.5})
    assert out["decision"] == DECISION_SCALE and out["uplift_pct"] == pytest.approx(15.0, abs=0.2)


# ── data layer ────────────────────────────────────────────────────────────────
@pytest.fixture()
def db():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True)
    s = sessionmaker(bind=eng, future=True)()
    try:
        yield s
    finally:
        s.close()


def test_create_record_assignment_idempotent(db):
    eid = ex.create_experiment(db, name="ranking-nudge", target_metric="conversion")
    assert eid
    assert ex.record_assignment(db, experiment_id=eid, subject_hash="u1", variant="treatment") is True
    assert ex.record_assignment(db, experiment_id=eid, subject_hash="u1", variant="treatment") is False  # idempotent
    db.commit()
    n = db.execute(text("SELECT COUNT(*) FROM experiment_assignment WHERE experiment_id=:e"), {"e": eid}).fetchone()[0]
    assert n == 1


def test_record_result(db):
    eid = ex.create_experiment(db, name="x", target_metric="rpv")
    rid = ex.record_result(db, experiment_id=eid, variant="treatment",
                           outcome={"decision": "scale", "uplift_pct": 12.0})
    assert rid
    row = db.execute(text("SELECT decision, uplift_pct FROM experiment_result WHERE id=:i"), {"i": rid}).fetchone()
    assert row[0] == "scale" and row[1] == 12.0


def test_data_layer_none_safe():
    assert ex.create_experiment(None, name="x", target_metric="m") is None
    assert ex.record_assignment(None, experiment_id="e", subject_hash="s", variant="v") is False
