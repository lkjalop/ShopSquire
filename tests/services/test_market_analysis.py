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

from src.app.services import market_analysis as ma
from src.app.services.market_analysis import (
    FINDING_CONVERSION_ANOMALY,
    FINDING_DEMAND_SHIFT,
    FINDING_INVENTORY_MISMATCH,
    analyze,
    detect_conversion_anomaly,
    detect_demand_shift,
    detect_inventory_demand_mismatch,
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


# ── analyze() composes + never raises ────────────────────────────────────────
def test_analyze_runs_all_and_is_safe():
    assert analyze([]) == []  # empty → no findings, no raise
    assert isinstance(analyze([{"bad": "row"}]), list)


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
