"""S4 typed shadow actions — findings become typed proposals that are LOGGED, never executed."""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.app.services import shadow_actions as sa
from src.app.services.market_analysis import MarketFinding, persist_findings


@pytest.fixture()
def db():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True)
    s = sessionmaker(bind=eng, future=True)()
    try:
        yield s
    finally:
        s.close()


# ── pure mapping ─────────────────────────────────────────────────────────────
def test_finding_types_map_to_typed_actions():
    findings = [
        MarketFinding("demand_shift", "SKU-1", "critical", 0.9, "demand spiking", {}, "daily"),
        MarketFinding("conversion_anomaly", None, "warn", 0.6, "conversions dipped", {}, "daily"),
        MarketFinding("inventory_demand_mismatch", "SKU-2", "warn", 0.8, "unmet demand", {}, "recent"),
    ]
    actions = sa.propose_from_findings(findings)
    by_type = {a.source_finding_type: a for a in actions}
    assert by_type["demand_shift"].action_type == sa.ACTION_ADJUST_RANKING
    assert by_type["conversion_anomaly"].action_type == sa.ACTION_REVISE_SUPPORT_COPY
    assert by_type["inventory_demand_mismatch"].action_type == sa.ACTION_SUPPRESS_LOW_STOCK
    # every proposal is a PROPOSAL — never executed
    assert all(a.status == "proposed" for a in actions)
    # ordered by magnitude desc (most salient first): the critical demand_shift leads
    assert actions[0].source_finding_type == "demand_shift"


def test_objection_and_funnel_findings_propose_support_copy_review():
    # David's deck Module 4: support objections + weak funnel points → a guidance/messaging review proposal
    findings = [
        MarketFinding("objection_cluster", "price", "critical", 0.9, "price raised 6x", {"theme": "price"}, "recent"),
        MarketFinding("funnel_dropoff", "payment", "warn", 0.7, "70% abandon", {"stage": "payment"}, "recent"),
    ]
    by_type = {a.source_finding_type: a for a in sa.propose_from_findings(findings)}
    assert by_type["objection_cluster"].action_type == sa.ACTION_REVISE_SUPPORT_COPY
    assert by_type["funnel_dropoff"].action_type == sa.ACTION_REVISE_SUPPORT_COPY
    assert by_type["objection_cluster"].direction == "review"  # log-only proposal through the gate
    assert by_type["objection_cluster"].target_ref == "price" and by_type["funnel_dropoff"].target_ref == "payment"


def test_direction_inferred_from_evidence():
    spike = sa.propose_from_findings([MarketFinding("demand_shift", "A", "warn", 0.7, "s", {"direction": "up"}, "d")])
    slowdown = sa.propose_from_findings([MarketFinding("demand_shift", "A", "warn", 0.7, "s", {"direction": "down"}, "d")])
    assert spike[0].direction == "boost" and slowdown[0].direction == "demote"
    # promotion always routes through the experiment gate
    assert spike[0].params["requires_experiment"] is True and spike[0].params["reversible"] is True


def test_unknown_finding_type_yields_no_proposal():
    assert sa.propose_from_findings([MarketFinding("mystery", "A", "warn", 0.5, "x", {}, "d")]) == []


# ── persistence (log-only) ───────────────────────────────────────────────────
def test_persist_and_load_then_supersede(db):
    a1 = sa.propose_from_findings([MarketFinding("demand_shift", "SKU-1", "warn", 0.5, "v1", {}, "daily")])
    assert sa.persist_proposals(db, a1) == 1
    db.commit()
    a2 = sa.propose_from_findings([MarketFinding("demand_shift", "SKU-1", "critical", 0.9, "v2", {}, "daily")])
    assert sa.persist_proposals(db, a2) == 1  # same (action,target) → supersedes v1
    db.commit()
    active = sa.load_recent_proposals(db)
    assert len(active) == 1 and active[0]["rationale"] == "v2"
    superseded = db.execute(text("SELECT COUNT(*) FROM shadow_action WHERE status='superseded'")).scalar()
    assert superseded == 1
    # INVARIANT: no row is ever 'executed'
    executed = db.execute(text("SELECT COUNT(*) FROM shadow_action WHERE status='executed'")).scalar()
    assert executed == 0


def test_generate_from_persisted_findings_is_log_only(db):
    persist_findings(db, [MarketFinding("inventory_demand_mismatch", "SKU-9", "critical", 0.9, "unmet", {}, "recent")])
    db.commit()
    result = sa.generate_shadow_actions(db)
    db.commit()
    assert result["proposed"] == 1 and result["by_action"].get("suppress_low_stock") == 1
    rows = sa.load_recent_proposals(db)
    assert rows and rows[0]["target_ref"] == "SKU-9" and rows[0]["status"] == "proposed"


def test_generate_safe_on_empty(db):
    assert sa.generate_shadow_actions(db) == {"proposed": 0, "by_action": {}}
    assert sa.generate_shadow_actions(None) == {"proposed": 0, "by_action": {}}


# ── structural safety: the module has NO execution path ──────────────────────
def test_module_imports_no_executor():
    import inspect
    src = inspect.getsource(sa)
    # the log-only invariant is structural: shadow_actions must not import/call a ranker, inventory
    # mutator, or copy writer. Guard against a future edit silently wiring execution.
    for forbidden in ("apply_experiment_nudge", "set_stock", "update_ranking", "execute_action",
                      "ranking_nudge", "inventory_query_service"):
        assert forbidden not in src, f"shadow_actions must stay log-only — found reference to {forbidden}"


def test_task_registered_and_default_off():
    from src.app.workers.celery_app import celery_app
    from src.app.tasks.shadow_action_tasks import generate_shadow_actions, _enabled
    assert "src.app.tasks.shadow_action_tasks" in (celery_app.conf.imports or ())
    assert _enabled() is False
    assert generate_shadow_actions.run() == {"skipped": "disabled"}


def test_segment_shift_maps_to_targeting_review_with_direction():
    from src.app.services.market_analysis import MarketFinding
    rising = MarketFinding("segment_shift", "enterprise", "critical", 0.9, "enterprise rising",
                           {"direction": "rising", "shift": 0.45})
    falling = MarketFinding("segment_shift", "smb", "warn", 0.6, "smb falling",
                            {"direction": "falling", "shift": -0.45})
    props = {p.target_ref: p for p in sa.propose_from_findings([rising, falling])}
    assert props["enterprise"].action_type == sa.ACTION_REVISE_SEGMENT_TARGETING
    assert props["enterprise"].direction == "boost"      # lean toward the rising segment
    assert props["smb"].direction == "demote"            # away from the falling one
    # shadow-only invariant: never executed; promotion goes through the experiment gate
    assert all(p.status == "proposed" and p.params.get("requires_experiment") for p in props.values())


def test_channel_performance_maps_to_prioritize_channel_with_direction():
    from src.app.services.market_analysis import MarketFinding
    over = MarketFinding("channel_performance", "paid", "warn", 0.7, "paid overperforming",
                         {"direction": "overperforming"})
    under = MarketFinding("channel_performance", "email", "critical", 0.6, "email underperforming",
                          {"direction": "underperforming"})
    props = {p.target_ref: p for p in sa.propose_from_findings([over, under])}
    assert props["paid"].action_type == sa.ACTION_PRIORITIZE_CHANNEL and props["paid"].direction == "boost"
    assert props["email"].direction == "demote"
    assert all(p.status == "proposed" and p.params.get("requires_experiment") for p in props.values())


def test_bundle_opportunity_maps_to_propose_bundle():
    from src.app.services.market_analysis import MarketFinding
    f = MarketFinding("bundle_opportunity", "A+B", "info", 0.4, "A + B co-purchased",
                      {"pair": ["A", "B"], "co_occurrence": 4, "direction": "bundle"})
    p = sa.propose_from_findings([f])[0]
    assert p.action_type == sa.ACTION_PROPOSE_BUNDLE and p.direction == "review"
    assert p.status == "proposed" and p.params.get("requires_experiment")
