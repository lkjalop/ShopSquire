"""Unit tests for the M3 market analysis engine (services/market_analysis.py).

Detectors use an injected anomaly_fn (deterministic) so findings are exercised without the real
statistical model. Covers demand shift, conversion-rate drop, unmet-demand mismatch, the min-history
gate, and the never-raises analyze().
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from datetime import date, timedelta

from src.app.services import market_analysis as ma
from src.app.services.market_analysis import (
    FINDING_COMPETITOR_UNDERCUT,
    FINDING_CONVERSION_ANOMALY,
    FINDING_DEMAND_FORECAST,
    FINDING_DEMAND_SHIFT,
    FINDING_INVENTORY_MISMATCH,
    FINDING_OBJECTION_CLUSTER,
    FINDING_SEASONAL_DEMAND,
    analyze,
    detect_competitor_undercut,
    detect_conversion_anomaly,
    detect_demand_forecast,
    detect_demand_shift,
    detect_inventory_demand_mismatch,
    detect_objection_cluster,
    detect_seasonal_demand,
    run_analysis,
)


def _anom(is_anom, conf=0.9, sev="warn", z=3.0):
    return SimpleNamespace(is_anomaly=is_anom, confidence=conf, severity=sev, z_score=z)


def _flag_last_outlier(series, domain):
    """Deterministic fake: flag an anomaly when the last point deviates >50% from the rest's mean."""
    rest = series[:-1] or [0.0]
    base = sum(rest) / len(rest) if rest else 0.0
    last = series[-1]
    return [_anom(base > 0 and (last > base * 1.5 or last < base * 0.5))]


def _demand(day, n):
    return [{"signal_type": "demand", "source": "search_events", "payload": {"query": "laptop", "result_count": 5},
             "occurred_at": f"{day}T10:00:00"} for _ in range(n)]


# ── demand shift ─────────────────────────────────────────────────────────────
def test_demand_shift_spike():
    sigs = (_demand("2026-06-20", 2) + _demand("2026-06-21", 2) + _demand("2026-06-22", 2)
            + _demand("2026-06-23", 2) + _demand("2026-06-24", 20))  # spike on the last day
    found = detect_demand_shift(sigs, anomaly_fn=_flag_last_outlier)
    assert len(found) == 1 and found[0].finding_type == FINDING_DEMAND_SHIFT
    assert "spike" in found[0].summary


def test_demand_shift_needs_min_history():
    assert detect_demand_shift(_demand("2026-06-24", 50), anomaly_fn=_flag_last_outlier) == []  # 1 day only


def test_demand_shift_slowdown_carries_direction_and_proposes_demote():
    # a SLOWDOWN must tag evidence direction='slowdown' so the shadow proposal DEMOTES, not boosts
    sigs = (_demand("2026-06-20", 20) + _demand("2026-06-21", 20) + _demand("2026-06-22", 20)
            + _demand("2026-06-23", 20) + _demand("2026-06-24", 2))  # collapse on the last day
    found = detect_demand_shift(sigs, anomaly_fn=_flag_last_outlier)
    assert len(found) == 1 and "slowdown" in found[0].summary
    assert found[0].evidence.get("direction") == "slowdown"  # the bug: direction was missing from evidence
    from src.app.services.shadow_actions import ACTION_ADJUST_RANKING, propose_from_findings
    proposals = propose_from_findings(found)
    assert proposals[0].action_type == ACTION_ADJUST_RANKING and proposals[0].direction == "demote"


def test_demand_shift_spike_proposes_boost():
    sigs = (_demand("2026-06-20", 2) + _demand("2026-06-21", 2) + _demand("2026-06-22", 2)
            + _demand("2026-06-23", 2) + _demand("2026-06-24", 20))
    found = detect_demand_shift(sigs, anomaly_fn=_flag_last_outlier)
    assert found[0].evidence.get("direction") == "spike"
    from src.app.services.shadow_actions import propose_from_findings
    assert propose_from_findings(found)[0].direction == "boost"


# ── conversion anomaly (drop only) ───────────────────────────────────────────
def test_conversion_drop_flagged():
    sigs = []
    for day, conv in [("2026-06-20", 5), ("2026-06-21", 5), ("2026-06-22", 5), ("2026-06-23", 5), ("2026-06-24", 0)]:
        sigs += _demand(day, 10)
        sigs += [{"signal_type": "conversion", "source": "conversion_event", "payload": {},
                  "occurred_at": f"{day}T11:00:00"} for _ in range(conv)]
    found = detect_conversion_anomaly(sigs, anomaly_fn=_flag_last_outlier)
    assert len(found) == 1 and found[0].finding_type == FINDING_CONVERSION_ANOMALY
    assert "drop" in found[0].summary


def test_conversion_rise_not_flagged():
    # rate rises on last day → not actionable, no finding even if the fake flags it
    sigs = []
    for day, conv in [("2026-06-20", 1), ("2026-06-21", 1), ("2026-06-22", 1), ("2026-06-23", 1), ("2026-06-24", 10)]:
        sigs += _demand(day, 10)
        sigs += [{"signal_type": "conversion", "source": "conversion_event", "payload": {},
                  "occurred_at": f"{day}T11:00:00"} for _ in range(conv)]
    assert detect_conversion_anomaly(sigs, anomaly_fn=_flag_last_outlier) == []


# ── inventory / unmet demand ─────────────────────────────────────────────────
def test_unmet_demand_mismatch():
    sigs = [{"signal_type": "demand", "source": "search_events",
             "payload": {"query": "framework 16", "result_count": 0}, "occurred_at": "2026-06-24T10:00:00"}
            for _ in range(4)]
    found = detect_inventory_demand_mismatch(sigs, min_unmet=3)
    assert len(found) == 1 and found[0].finding_type == FINDING_INVENTORY_MISMATCH
    assert found[0].entity_ref == "framework 16" and found[0].evidence["zero_result_searches"] == 4


def test_unmet_demand_below_threshold():
    sigs = [{"signal_type": "demand", "source": "search_events",
             "payload": {"query": "rare", "result_count": 0}, "occurred_at": "2026-06-24T10:00:00"}]
    assert detect_inventory_demand_mismatch(sigs, min_unmet=3) == []


# ── demand forecast (forward-looking) ────────────────────────────────────────
def _demand_days(pairs):
    out = []
    for day, n in pairs:
        out += _demand(day, n)
    return out


def test_demand_forecast_projected_surge_boosts():
    sigs = _demand_days([("2026-06-20", 5), ("2026-06-21", 5), ("2026-06-22", 5), ("2026-06-23", 5)])
    found = detect_demand_forecast(sigs, forecast_fn=lambda s: (30.0, "test"))  # 30 vs ~5 baseline
    assert len(found) == 1 and found[0].finding_type == FINDING_DEMAND_FORECAST
    assert found[0].evidence["direction"] == "spike"
    from src.app.services.shadow_actions import ACTION_ADJUST_RANKING, propose_from_findings
    p = propose_from_findings(found)
    assert p[0].action_type == ACTION_ADJUST_RANKING and p[0].direction == "boost"


def test_demand_forecast_projected_shortfall_demotes():
    sigs = _demand_days([("2026-06-20", 20), ("2026-06-21", 20), ("2026-06-22", 20), ("2026-06-23", 20)])
    found = detect_demand_forecast(sigs, forecast_fn=lambda s: (2.0, "test"))  # 2 vs ~20 baseline
    assert len(found) == 1 and found[0].evidence["direction"] == "slowdown"
    from src.app.services.shadow_actions import propose_from_findings
    assert propose_from_findings(found)[0].direction == "demote"


def test_demand_forecast_within_band_is_silent():
    sigs = _demand_days([("2026-06-20", 10), ("2026-06-21", 10), ("2026-06-22", 10), ("2026-06-23", 10)])
    assert detect_demand_forecast(sigs, forecast_fn=lambda s: (10.0, "test")) == []  # ratio 1.0


def test_demand_forecast_default_ewma_on_rising_series():
    # low baseline then a sustained recent jump — what a one-step forecast is meant to catch (a smooth
    # ramp would stay inside the band: EWMA lags, so the projection sits near the mean).
    sigs = _demand_days([("2026-06-20", 3), ("2026-06-21", 3), ("2026-06-22", 3), ("2026-06-23", 3),
                         ("2026-06-24", 3), ("2026-06-25", 3), ("2026-06-26", 30), ("2026-06-27", 30),
                         ("2026-06-28", 30)])
    found = detect_demand_forecast(sigs)  # default EWMA, no inject
    assert found and found[0].evidence["method"] == "ewma" and found[0].evidence["direction"] == "spike"


def test_demand_forecast_needs_min_history():
    assert detect_demand_forecast(_demand("2026-06-24", 50), forecast_fn=lambda s: (99.0, "t")) == []


# ── seasonal day-of-week ─────────────────────────────────────────────────────
def test_seasonal_demand_peak_weekday():
    # 14 consecutive days; the two Saturdays (idx 5, 12 from a Monday start) carry the spike
    start = date(2026, 6, 15)  # Monday
    pairs = []
    for i in range(14):
        d = (start + timedelta(days=i)).isoformat()
        pairs.append((d, 20 if i in (5, 12) else 2))
    found = detect_seasonal_demand(_demand_days(pairs))
    assert len(found) == 1 and found[0].finding_type == FINDING_SEASONAL_DEMAND
    assert found[0].evidence["peak_weekday"] == "Saturday" and found[0].evidence["ratio"] >= 1.4


def test_seasonal_demand_needs_min_days():
    pairs = [((date(2026, 6, 15) + timedelta(days=i)).isoformat(), 5) for i in range(5)]
    assert detect_seasonal_demand(_demand_days(pairs)) == []  # < 7 days


# ── competitor undercut ──────────────────────────────────────────────────────
def _competitor(ent, ours, theirs, occ="2026-06-25T09:00:00"):
    return [{"signal_type": "competitor", "source": "competitor_feed",
             "payload": {"entity_ref": ent, "our_price_cents": ours, "competitor_price_cents": theirs,
                         "competitor": "rival.example"}, "occurred_at": occ}]


def test_competitor_undercut_flagged_critical():
    found = detect_competitor_undercut(_competitor("SKU-1", 150000, 124900))  # ~17% under
    assert len(found) == 1 and found[0].finding_type == FINDING_COMPETITOR_UNDERCUT
    assert found[0].entity_ref == "SKU-1" and found[0].severity == "critical"


def test_competitor_no_undercut_when_we_are_cheaper():
    assert detect_competitor_undercut(_competitor("SKU-1", 100000, 110000)) == []


def test_competitor_uses_latest_observation():
    sigs = (_competitor("SKU-1", 150000, 149000, "2026-06-20T09:00:00")   # 0.7% — below threshold
            + _competitor("SKU-1", 150000, 120000, "2026-06-25T09:00:00"))  # later: 20% under
    found = detect_competitor_undercut(sigs)
    assert len(found) == 1 and found[0].evidence["competitor_price_cents"] == 120000


# ── objection clustering ─────────────────────────────────────────────────────
def _objections(theme, n):
    return [{"signal_type": "support_objection", "source": "support_inbox",
             "payload": {"theme": theme}, "occurred_at": "2026-06-25T12:00:00"} for _ in range(n)]


def test_objection_cluster_flagged():
    found = detect_objection_cluster(_objections("price", 6) + _objections("delivery", 1))
    assert len(found) == 1 and found[0].entity_ref == "price" and found[0].severity == "critical"


def test_objection_below_threshold_silent():
    assert detect_objection_cluster(_objections("price", 2)) == []


# ── funnel drop-off ──────────────────────────────────────────────────────────
def _funnel(stage, entered, abandoned):
    return [{"signal_type": "funnel", "source": "funnel_events",
             "payload": {"stage": stage, "entered": entered, "abandoned": abandoned},
             "occurred_at": "2026-06-26T08:00:00"}]


def test_funnel_dropoff_flagged():
    from src.app.services.market_analysis import FINDING_FUNNEL_DROPOFF, detect_funnel_dropoff
    found = detect_funnel_dropoff(_funnel("payment", 60, 42))  # 70% drop-off
    assert len(found) == 1 and found[0].finding_type == FINDING_FUNNEL_DROPOFF
    assert found[0].entity_ref == "payment" and found[0].severity == "warn"
    assert found[0].evidence["rate"] == 0.7


def test_funnel_critical_above_75pct():
    from src.app.services.market_analysis import detect_funnel_dropoff
    assert detect_funnel_dropoff(_funnel("payment", 100, 80))[0].severity == "critical"


def test_funnel_below_min_volume_ignored():
    from src.app.services.market_analysis import detect_funnel_dropoff
    assert detect_funnel_dropoff(_funnel("payment", 4, 4)) == []  # tiny sample can't trip it


def test_funnel_healthy_stage_not_flagged():
    from src.app.services.market_analysis import detect_funnel_dropoff
    assert detect_funnel_dropoff(_funnel("cart", 100, 10)) == []  # 10% drop-off → fine


# ── analyze() composes + never raises ────────────────────────────────────────
def test_analyze_runs_all_and_is_safe():
    assert analyze([]) == []  # empty → no findings, no raise
    assert isinstance(analyze([{"bad": "row"}]), list)


def test_analyze_composes_new_detectors():
    sigs = (_demand_days([("2026-06-20", 5), ("2026-06-21", 5), ("2026-06-22", 5), ("2026-06-23", 5)])
            + _competitor("SKU-1", 150000, 120000) + _objections("price", 6))
    types = {f.finding_type for f in analyze(sigs, forecast_fn=lambda s: (30.0, "t"))}
    assert {FINDING_DEMAND_FORECAST, FINDING_COMPETITOR_UNDERCUT, FINDING_OBJECTION_CLUSTER} <= types


# ── DB entry point ───────────────────────────────────────────────────────────
def test_run_analysis_reads_market_signal():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True)
    db = sessionmaker(bind=eng, future=True)()
    from src.app.services.market_signal import ensure_table
    ensure_table(db)
    for i, day in enumerate(["2026-06-20", "2026-06-21", "2026-06-22", "2026-06-23", "2026-06-24"]):
        n = 2 if i < 4 else 20
        for j in range(n):
            db.execute(text("INSERT INTO market_signal (id, signal_type, source, dedup_key, trust_score, "
                            "payload_json, occurred_at) VALUES (:id,'demand','search_events',:k,0.8,'{}',:occ)"),
                       {"id": f"{day}-{j}", "k": f"{day}-{j}", "occ": f"{day}T10:00:00"})
    db.commit()
    findings = run_analysis(db, anomaly_fn=_flag_last_outlier)
    assert any(f.finding_type == FINDING_DEMAND_SHIFT for f in findings)
    db.close()
