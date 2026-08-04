"""Unit tests for the latency bench aggregation (the part that must be correct without a stack)."""
from __future__ import annotations

from scripts.bench_recommend import aggregate, percentile


def test_percentile_nearest_rank():
    xs = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]
    assert percentile(xs, 50) == 50
    assert percentile(xs, 95) == 100
    assert percentile([], 50) == 0.0
    assert percentile([42], 95) == 42


def test_aggregate_per_stage_p50_p95():
    samples = [
        {"route_total_ms": 100, "summary_ms": 80, "nlp_ms": 5},
        {"route_total_ms": 200, "summary_ms": 150, "nlp_ms": 6},
        {"route_total_ms": 300, "summary_ms": 250, "nlp_ms": 7, "guard_ms": 2},
    ]
    agg = aggregate(samples)
    assert agg["route_total_ms"]["p50"] == 200
    assert agg["route_total_ms"]["max"] == 300
    assert agg["summary_ms"]["n"] == 3
    assert agg["guard_ms"]["n"] == 1  # sparse stage counted only where present
    assert "nlp_ms" in agg


def test_aggregate_ignores_non_numeric_and_empty():
    assert aggregate([]) == {}
    assert aggregate([{"x": "not a number"}, {"route_total_ms": 50}])["route_total_ms"]["p50"] == 50
