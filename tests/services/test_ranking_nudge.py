"""Unit tests for the reversible ranking nudge (services/ranking_nudge.py) + experiment live gate."""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.app.services import experiments as ex
from src.app.services.ranking_nudge import (
    apply_experiment_nudge, apply_sales_response_nudge, revert_nudge)


def _results():
    # B is recalled; without a boost A(0.9) > B(0.85) > C(0.8)
    return [{"sku": "A", "score": 0.90}, {"sku": "B", "score": 0.85}, {"sku": "C", "score": 0.80}]


def test_control_user_untouched_identity():
    r = _results()
    out = apply_experiment_nudge(r, recall_ids=["B"], assignment="control", live=True)
    assert out is r  # identity — control is never nudged


def test_non_live_untouched_identity():
    r = _results()
    out = apply_experiment_nudge(r, recall_ids=["B"], assignment="treatment", live=False)
    assert out is r


def test_no_recall_ids_untouched():
    r = _results()
    assert apply_experiment_nudge(r, recall_ids=[], assignment="treatment", live=True) is r


def test_treatment_live_boosts_and_reorders():
    out = apply_experiment_nudge(_results(), recall_ids=["B"], assignment="treatment", live=True, max_boost=0.1)
    skus = [r["sku"] for r in out]
    assert skus[0] == "B"  # B (0.85+0.1=0.95) now outranks A (0.90)
    boosted = next(r for r in out if r["sku"] == "B")
    assert boosted["_nudge_delta"] == 0.1
    assert "market-intel boost (experiment)" in boosted["why"]


def test_boost_is_bounded():
    out = apply_experiment_nudge(_results(), recall_ids=["B"], assignment="treatment", live=True, max_boost=0.05)
    boosted = next(r for r in out if r["sku"] == "B")
    assert boosted["_nudge_delta"] == 0.05  # exactly the cap, never more


def test_revert_nudge_restores_original():
    nudged = apply_experiment_nudge(_results(), recall_ids=["B"], assignment="treatment", live=True, max_boost=0.1)
    restored = revert_nudge(nudged)
    skus = [r["sku"] for r in restored]
    assert skus == ["A", "B", "C"]  # original order restored
    assert all("_nudge_delta" not in r for r in restored)
    assert all("market-intel boost (experiment)" not in (r.get("why") or []) for r in restored)


# ── M5 demand-aware nudge (surplus boosts, can't-ship shortage recedes) ───────
def test_sales_response_nudge_boosts_surplus_demotes_shortage():
    # A(0.90) surplus→boost, C(0.80) shortage→suppress; B steady
    out = apply_sales_response_nudge(
        _results(), bias_by_sku={"A": "boost", "C": "suppress", "B": "steady"}, max_delta=0.05)
    a = next(r for r in out if r["sku"] == "A")
    c = next(r for r in out if r["sku"] == "C")
    assert a["_sales_response_delta"] == 0.05 and c["_sales_response_delta"] == -0.05
    assert a["score"] == pytest.approx(0.95) and c["score"] == pytest.approx(0.75)   # bounded ± delta
    assert "market-intel (demand-aware) ↑" in a["why"] and "market-intel (demand-aware) ↓" in c["why"]


def test_sales_response_nudge_identity_when_all_steady():
    r = _results()
    assert apply_sales_response_nudge(r, bias_by_sku={"A": "steady", "B": "steady"}) is r


def test_sales_response_nudge_is_bounded_by_item_cap():
    out = apply_sales_response_nudge(
        _results(), bias_by_sku={"A": "boost", "B": "boost", "C": "boost"}, max_delta=0.05, max_nudged_items=1)
    assert sum(1 for r in out if r.get("_sales_response_delta")) == 1   # only 1 nudged, cap respected


def test_revert_nudge_undoes_sales_response_delta():
    nudged = apply_sales_response_nudge(
        _results(), bias_by_sku={"A": "boost", "C": "suppress"}, max_delta=0.05)
    restored = revert_nudge(nudged)
    assert [r["sku"] for r in restored] == ["A", "B", "C"]              # original order back
    assert all("_sales_response_delta" not in r for r in restored)
    assert all(not any(str(w).startswith("market-intel (demand-aware)") for w in (r.get("why") or []))
               for r in restored)


# ── experiment live gate ──────────────────────────────────────────────────────
@pytest.fixture()
def db():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True)
    s = sessionmaker(bind=eng, future=True)()
    try:
        yield s
    finally:
        s.close()


def test_is_experiment_live_reflects_status(db):
    eid = ex.create_experiment(db, name="ranking_nudge_v1", target_metric="conversion", status="draft")
    db.commit()
    assert ex.is_experiment_live(db, "ranking_nudge_v1") is False  # draft
    ex.set_status(db, experiment_id="ranking_nudge_v1", status="live")
    db.commit()
    assert ex.is_experiment_live(db, "ranking_nudge_v1") is True
    # the reversibility lever — flip to reverted → no longer live
    ex.set_status(db, experiment_id=eid, status="reverted")
    db.commit()
    assert ex.is_experiment_live(db, eid) is False


def test_is_experiment_live_unknown_is_false(db):
    assert ex.is_experiment_live(db, "nope") is False
    assert ex.is_experiment_live(None, "x") is False
