"""Unit tests for the attribution core (services/attribution.py).

Isolated in-memory SQLite — no app/engine dependency. Verifies the capture loop: record a
decision, attribute an order back to it (by trace_id, with uid fallback), idempotency per
order, the no-match path, bounded reward, and never-raises on bad input.
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.app.services import attribution
from src.app.services.attribution import AttributionResult


@pytest.fixture()
def db():
    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session = sessionmaker(bind=eng, future=True)()
    try:
        yield session
    finally:
        session.close()


def test_ensure_tables_idempotent(db):
    attribution.ensure_tables(db)
    attribution.ensure_tables(db)  # second call must not raise
    # both tables exist
    for tbl in ("recommendation_decision", "conversion_event"):
        db.execute(text(f"SELECT COUNT(*) FROM {tbl}"))


def test_record_decision_persists(db):
    rid = attribution.record_decision(
        db, trace_id="T1", decision_id="D1", uid_hash="u1",
        skus=["A", "B"], arm="balanced", variant="control", context={"budget_max": 1500},
    )
    assert rid
    row = db.execute(text("SELECT trace_id, decision_id, arm FROM recommendation_decision WHERE id=:i"),
                     {"i": rid}).fetchone()
    assert row[0] == "T1" and row[1] == "D1" and row[2] == "balanced"


def test_attribute_order_by_trace(db):
    attribution.record_decision(db, trace_id="T2", decision_id="D2", uid_hash="u2", skus=["A", "B"])
    res = attribution.attribute_order(
        db, order_id="O2", trace_id="T2", uid_hash="u2", value_cents=119900, line_skus=["A"],
    )
    assert res.attributed is True
    assert res.decision_id == "D2"
    assert res.attributed_skus == ["A"]
    assert res.value_cents == 119900
    assert attribution.reward_from_outcome(res) == 1.0


def test_attribute_order_uid_fallback_when_no_trace(db):
    attribution.record_decision(db, trace_id="T3", decision_id="D3", uid_hash="u3", skus=["X"])
    res = attribution.attribute_order(db, order_id="O3", trace_id=None, uid_hash="u3", line_skus=["X"])
    assert res.attributed is True and res.decision_id == "D3"


def test_attribute_order_idempotent_per_order(db):
    attribution.record_decision(db, trace_id="T4", decision_id="D4", uid_hash="u4", skus=["A"])
    first = attribution.attribute_order(db, order_id="O4", trace_id="T4", uid_hash="u4")
    second = attribution.attribute_order(db, order_id="O4", trace_id="T4", uid_hash="u4")
    assert first.attributed is True
    assert second.attributed is False and second.reason == "already_attributed"
    n = db.execute(text("SELECT COUNT(*) FROM conversion_event WHERE order_id='O4'")).fetchone()[0]
    assert n == 1  # exactly one conversion row


def test_attribute_order_no_matching_decision(db):
    attribution.ensure_tables(db)
    res = attribution.attribute_order(db, order_id="O5", trace_id="UNKNOWN", uid_hash="nobody")
    assert res.attributed is False and res.reason == "no_matching_decision"
    assert attribution.reward_from_outcome(res) == 0.0


def test_record_decision_never_raises_on_bad_db():
    assert attribution.record_decision(None, trace_id="T", decision_id="D", uid_hash="u") is None


def test_attribute_order_never_raises_on_bad_db():
    res = attribution.attribute_order(None, order_id="O")
    assert isinstance(res, AttributionResult) and res.attributed is False


def test_reward_bounded():
    assert attribution.reward_from_outcome(AttributionResult(attributed=True)) == 1.0
    assert attribution.reward_from_outcome(AttributionResult(attributed=False)) == 0.0
    assert attribution.reward_from_outcome("not-a-result") == 0.0  # type: ignore[arg-type]
