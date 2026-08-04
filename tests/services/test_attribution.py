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


def test_arm_for_trace_resolves_recorded_arm(db):
    attribution.record_decision(db, trace_id="AT", decision_id="AD", uid_hash="u", skus=["S"], arm="explore_novelty")
    db.commit()
    assert attribution.arm_for_trace(db, "AT") == "explore_novelty"


def test_arm_for_trace_defaults_balanced(db):
    attribution.ensure_tables(db)
    assert attribution.arm_for_trace(db, "UNKNOWN") == "balanced"
    assert attribution.arm_for_trace(db, None) == "balanced"
    assert attribution.arm_for_trace(None, "x") == "balanced"


def test_reward_bounded():
    assert attribution.reward_from_outcome(AttributionResult(attributed=True)) == 1.0
    assert attribution.reward_from_outcome(AttributionResult(attributed=False)) == 0.0
    assert attribution.reward_from_outcome("not-a-result") == 0.0  # type: ignore[arg-type]


# ── E3 reward feed ────────────────────────────────────────────────────────────
def _settled_conversion(db, *, n, decision_id, uid_hash, sku, arm="balanced", converted="2020-01-01T00:00:00"):
    attribution.record_decision(db, trace_id=f"RT{n}", decision_id=decision_id, uid_hash=uid_hash,
                                skus=[sku], arm=arm)
    attribution.attribute_order(db, order_id=f"RO{n}", trace_id=f"RT{n}", uid_hash=uid_hash,
                                value_cents=100, line_skus=[sku], converted_at=converted)


def test_reward_feed_rewards_settled_conversion(db):
    attribution.ensure_tables(db)
    _settled_conversion(db, n=1, decision_id="RD1", uid_hash="u1", sku="S1", arm="price_value")
    db.commit()
    calls = []
    def fake(db, *, uid_hash, sku, arm, reward, context):
        calls.append((uid_hash, sku, arm, reward))
    s = attribution.run_reward_feed(db, tenant_id="default", settle_cutoff_iso="2099-01-01T00:00:00", bandit_reward_fn=fake)
    assert s["rewarded"] == 1
    assert calls == [("u1", "S1", "price_value", 1.0)]
    # idempotent: a second pass rewards nothing (rewarded_at marker).
    s2 = attribution.run_reward_feed(db, tenant_id="default", settle_cutoff_iso="2099-01-01T00:00:00", bandit_reward_fn=fake)
    assert s2["rewarded"] == 0 and len(calls) == 1


def test_reward_feed_skips_unsettled(db):
    attribution.ensure_tables(db)
    _settled_conversion(db, n=2, decision_id="RD2", uid_hash="u2", sku="S2", converted="2099-12-31T00:00:00")
    db.commit()
    calls = []
    s = attribution.run_reward_feed(db, tenant_id="default", settle_cutoff_iso="2000-01-01T00:00:00",
                                    bandit_reward_fn=lambda *a, **k: calls.append(1))
    assert s["rewarded"] == 0 and not calls  # converted_at is after the settle cutoff → not yet settled


def test_reward_feed_per_uid_cap(db):
    attribution.ensure_tables(db)
    for i in range(3):
        _settled_conversion(db, n=10 + i, decision_id=f"CD{i}", uid_hash="capuid", sku="SC")
    db.commit()
    calls = []
    s = attribution.run_reward_feed(db, tenant_id="default", settle_cutoff_iso="2099-01-01T00:00:00", per_uid_cap=2,
                                    bandit_reward_fn=lambda db, **k: calls.append(1))
    assert s["rewarded"] == 2 and s["skipped_cap"] == 1  # one uid's influence is capped per batch


def test_reward_feed_marks_no_decision_and_skips(db):
    attribution.ensure_tables(db)
    # a conversion with no matching decision (orphan) is consumed but not rewarded.
    attribution.attribute_order(db, order_id="ORPHAN", trace_id=None, uid_hash="ux", line_skus=["S"],
                                converted_at="2020-01-01T00:00:00")
    # attribute_order with no decision returns no row, so insert an orphan conversion directly:
    db.execute(text(
        "INSERT INTO conversion_event (id, decision_id, order_id, uid_hash, attributed_skus_json, "
        "value_cents, converted_at) VALUES ('orph','MISSING','O9','ux','[\"S\"]',1,'2020-01-01T00:00:00')"))
    db.commit()
    s = attribution.run_reward_feed(db, tenant_id="default", settle_cutoff_iso="2099-01-01T00:00:00",
                                    bandit_reward_fn=lambda *a, **k: None)
    assert s["skipped_no_decision"] >= 1 and s["rewarded"] == 0


def test_reward_feed_never_joins_same_decision_id_across_tenants(db):
    attribution.record_decision(
        db, trace_id="shared-trace", decision_id="shared-decision",
        uid_hash="tenant-a-user", skus=["A"], arm="tenant-a-arm",
        tenant_id="tenant-a",
    )
    attribution.record_decision(
        db, trace_id="shared-trace", decision_id="shared-decision",
        uid_hash="tenant-b-user", skus=["B"], arm="tenant-b-arm",
        tenant_id="tenant-b",
    )
    attribution.attribute_order(
        db, order_id="tenant-a-order", trace_id="shared-trace",
        uid_hash="tenant-a-user", line_skus=["A"],
        converted_at="2020-01-01T00:00:00", tenant_id="tenant-a",
    )
    attribution.attribute_order(
        db, order_id="tenant-b-order", trace_id="shared-trace",
        uid_hash="tenant-b-user", line_skus=["B"],
        converted_at="2020-01-01T00:00:00", tenant_id="tenant-b",
    )
    db.commit()
    calls = []
    summary = attribution.run_reward_feed(
        db,
        tenant_id="tenant-a",
        settle_cutoff_iso="2099-01-01T00:00:00",
        bandit_reward_fn=lambda db, **kwargs: calls.append(kwargs),
    )
    assert summary["processed"] == 1
    assert summary["rewarded"] == 1
    assert [(c["uid_hash"], c["sku"], c["arm"]) for c in calls] == [
        ("tenant-a-user", "A", "tenant-a-arm"),
    ]
    tenant_b_rewarded = db.execute(text(
        "SELECT rewarded_at FROM conversion_event "
        "WHERE tenant_id='tenant-b' AND order_id='tenant-b-order'"
    )).scalar()
    assert tenant_b_rewarded is None


def test_arm_for_trace_is_tenant_scoped(db):
    attribution.record_decision(
        db, trace_id="same-trace", decision_id="A", uid_hash="a",
        skus=["A"], arm="price_value", tenant_id="tenant-a",
    )
    attribution.record_decision(
        db, trace_id="same-trace", decision_id="B", uid_hash="b",
        skus=["B"], arm="explore_novelty", tenant_id="tenant-b",
    )
    db.commit()
    assert attribution.arm_for_trace(
        db, "same-trace", tenant_id="tenant-a",
    ) == "price_value"
    assert attribution.arm_for_trace(
        db, "same-trace", tenant_id="tenant-b",
    ) == "explore_novelty"


def test_conversion_attributes_back_to_adaptation_exposure(db):
    """M6 close-the-loop: a decision-turn EXPOSED to an adaptation (context.adaptations, ref → segment)
    must, on conversion, append attribution_event rows keyed to the ADAPTATION ref — the metric feed the
    uplift evaluation reads. One row per adaptation, value = the order's value, segment = the exposure."""
    attribution.record_decision(
        db, trace_id="T-m6", decision_id="D-m6", uid_hash="u6", skus=["A"],
        context={"adaptations": {"ranking_nudge_v1": "treatment", "sales_response": "rising"}},
    )
    res = attribution.attribute_order(db, order_id="O-m6", trace_id="T-m6", uid_hash="u6",
                                      value_cents=250000, line_skus=["A"])
    assert res.attributed is True
    rows = db.execute(text("SELECT decision_ref, metric, value, segment FROM attribution_event "
                           "ORDER BY decision_ref")).fetchall()
    assert [(r[0], r[1], r[2], r[3]) for r in rows] == [
        ("ranking_nudge_v1", "conversion_value_cents", 250000.0, "treatment"),
        ("sales_response", "conversion_value_cents", 250000.0, "rising"),
    ]
    # rollup reader: grouped per (ref, metric, segment) with count + sum
    from src.app.services.market_outcome import load_attribution_rollup
    roll = {r["decision_ref"]: r for r in load_attribution_rollup(db)}
    assert roll["ranking_nudge_v1"]["events"] == 1 and roll["ranking_nudge_v1"]["total_value"] == 250000.0


def test_conversion_without_exposure_writes_no_attribution_events(db):
    from src.app.services import market_outcome as mo
    mo.ensure_tables(db)  # table must exist to prove it stays EMPTY
    attribution.record_decision(db, trace_id="T-plain", decision_id="D-plain", uid_hash="u7", skus=["A"],
                                context={"budget_max": 1500})
    res = attribution.attribute_order(db, order_id="O-plain", trace_id="T-plain", uid_hash="u7",
                                      value_cents=9900, line_skus=["A"])
    assert res.attributed is True
    n = db.execute(text("SELECT COUNT(*) FROM attribution_event")).scalar()
    assert n == 0
