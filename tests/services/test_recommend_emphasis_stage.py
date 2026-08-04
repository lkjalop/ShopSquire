"""Phase-3 storefront-emphasis lever — flag-gated, experiment-gated, reversible, measured, profile-sourced.
Default-off must be byte-identical; the apply path requires a LIVE experiment + TREATMENT + gate ALLOW."""
from __future__ import annotations

from src.app.models.db import db_session
from src.app.services import experiment_console
from src.app.services.experiment_ops import canary_assignment
from src.app.services.recommend_emphasis_stage import apply_storefront_emphasis as ap

_VARIANTS = {"value": "Great value.", "urgency": "Moving fast.", "features": "Spec-forward."}


def _prof(key, default=None):
    return _VARIANTS if key == "storefront_emphasis_variants" else default


def _treatment_subject(exp: str) -> str:
    """A subject the real canary split deterministically lands in TREATMENT (fraction=1.0 ⇒ ~50%)."""
    for i in range(500):
        s = f"subj-{i}"
        if canary_assignment(experiment_id=exp, subject=s, canary_fraction=1.0) == "treatment":
            return s
    raise AssertionError("no treatment subject found")


def _promote(db, experiment_id: str) -> None:
    experiment_console.promote(
        db,
        tenant_id="default",
        experiment_id=experiment_id,
        baseline={"metric": "conversion", "window": "pre_activation"},
        eligibility={"surface": "storefront", "cohort": "test"},
        min_samples=2,
        min_window_seconds=60,
        rollback_threshold_pct=2.0,
        guardrails={"margin": {"minimum_delta_pct": -2.0}},
        terminal_policy={"allowed": ["keep", "scale", "revise", "revert"]},
    )


def test_flag_off_is_byte_identical_noop():
    p = {"right_panel": {"mode": "shopping"}}
    ap(p, flags={}, uid_hash="u1", profile_fn=_prof)
    assert p == {"right_panel": {"mode": "shopping"}}


def test_no_right_panel_is_noop():
    p = {}
    ap(p, flags={"STOREFRONT_EMPHASIS_EXPERIMENT_ENABLED": "1"}, uid_hash="u1", profile_fn=_prof)
    assert p == {}


def test_no_profile_variants_is_noop():
    p = {"right_panel": {"mode": "shopping"}}
    ap(p, flags={"STOREFRONT_EMPHASIS_EXPERIMENT_ENABLED": "1"}, uid_hash="u1",
       profile_fn=lambda k, default=None: default)
    assert "emphasis" not in p["right_panel"] and "storefront_emphasis" not in p


def test_not_live_records_but_does_not_apply():
    p = {"right_panel": {"mode": "shopping"}}
    ap(p, flags={"STOREFRONT_EMPHASIS_EXPERIMENT_ENABLED": "1", "STOREFRONT_EMPHASIS_CANARY_FRACTION": "1.0",
                 "STOREFRONT_EMPHASIS_EXPERIMENT_ID": "emph-notlive"}, uid_hash="u-x", profile_fn=_prof)
    assert (p.get("storefront_emphasis") or {}).get("applied") is False
    assert "emphasis" not in p["right_panel"]


def test_live_treatment_applies_profile_copy_and_is_gated():
    exp = "storefront_emphasis_test_live"
    with db_session() as db:
        _promote(db, exp)
        db.commit()
    p = {"right_panel": {"mode": "shopping"}}
    ap(p, flags={"STOREFRONT_EMPHASIS_EXPERIMENT_ENABLED": "1", "STOREFRONT_EMPHASIS_CANARY_FRACTION": "1.0",
                 "STOREFRONT_EMPHASIS_EXPERIMENT_ID": exp}, uid_hash=_treatment_subject(exp), profile_fn=_prof)
    emph = p["right_panel"].get("emphasis") or {}
    assert emph.get("applied") is True and emph.get("variant") == "treatment" and emph.get("live") is True
    assert emph.get("text") in _VARIANTS.values() and emph.get("key") in _VARIANTS
    assert emph.get("gate")


def test_revert_disables_the_lever_globally():
    exp = "storefront_emphasis_test_revert"
    with db_session() as db:
        _promote(db, exp)
        db.commit()
    subject = _treatment_subject(exp)  # would be treatment IF live; revert must still suppress it
    with db_session() as db:
        experiment_console.revert(db, tenant_id="default", experiment_id=exp)
        db.commit()
    p = {"right_panel": {"mode": "shopping"}}
    ap(p, flags={"STOREFRONT_EMPHASIS_EXPERIMENT_ENABLED": "1", "STOREFRONT_EMPHASIS_CANARY_FRACTION": "1.0",
                 "STOREFRONT_EMPHASIS_EXPERIMENT_ID": exp}, uid_hash=subject, profile_fn=_prof)
    assert "emphasis" not in p["right_panel"]
