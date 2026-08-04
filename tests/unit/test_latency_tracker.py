"""Tests for the latency tracker (p50/p95/p99 percentile measurement)."""
import pytest
from src.app.observability.latency_tracker import LatencyTracker, LatencyTimer, get_recommend_tracker


class TestLatencyTracker:
    def test_empty_tracker_returns_none_percentiles(self):
        t = LatencyTracker("test")
        p = t.percentiles()
        assert p["count"] == 0
        assert p["p50_ms"] is None
        assert p["p95_ms"] is None
        assert p["p99_ms"] is None

    def test_single_record(self):
        t = LatencyTracker("test")
        t.record(42.0)
        p = t.percentiles("cold")
        assert p["count"] == 1
        assert p["p50_ms"] == 42.0

    def test_warm_vs_cold_separation(self):
        t = LatencyTracker("test")
        t.record(100.0, cache_hit=False)
        t.record(5.0, cache_hit=True)
        cold = t.percentiles("cold")
        warm = t.percentiles("warm")
        combined = t.percentiles("all")
        assert cold["count"] == 1
        assert cold["p50_ms"] == 100.0
        assert warm["count"] == 1
        assert warm["p50_ms"] == 5.0
        assert combined["count"] == 2

    def test_percentiles_with_many_samples(self):
        t = LatencyTracker("test", window=1000)
        for i in range(100):
            t.record(float(i + 1))  # 1..100ms
        p = t.percentiles("cold")
        assert p["count"] == 100
        # p50 of 1..100 = ~50
        assert 49 <= p["p50_ms"] <= 51
        # p95 of 1..100 = ~95
        assert 94 <= p["p95_ms"] <= 96
        # p99 of 1..100 = ~99
        assert 98 <= p["p99_ms"] <= 100

    def test_window_eviction(self):
        t = LatencyTracker("test", window=10)
        for i in range(20):
            t.record(float(i))
        # Only last 10 should remain (10..19)
        p = t.percentiles("cold")
        assert p["count"] == 10
        assert p["min_ms"] == 10.0
        assert p["max_ms"] == 19.0

    def test_summary_structure(self):
        t = LatencyTracker("test")
        t.record(50.0, cache_hit=False)
        t.record(10.0, cache_hit=True)
        s = t.summary()
        assert s["pipeline"] == "test"
        assert "warm" in s
        assert "cold" in s
        assert "combined" in s

    def test_reset(self):
        t = LatencyTracker("test")
        t.record(50.0)
        t.reset()
        assert t.percentiles()["count"] == 0

    def test_latency_timer_context_manager(self):
        t = LatencyTracker("test")
        with LatencyTimer(t, cache_hit=False):
            pass  # trivial operation
        p = t.percentiles("cold")
        assert p["count"] == 1
        assert p["p50_ms"] >= 0

    def test_singleton_tracker(self):
        t1 = get_recommend_tracker()
        t2 = get_recommend_tracker()
        assert t1 is t2
