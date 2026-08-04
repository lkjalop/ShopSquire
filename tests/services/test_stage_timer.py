"""0.5 — StageTimer records stage ms; summarize_timing surfaces unaccounted time."""
from __future__ import annotations

import time

from src.app.observability.stage_timer import StageTimer, summarize_timing


def test_stage_timer_records_key():
    tb: dict = {}
    with StageTimer(tb, "summary_ms"):
        time.sleep(0.01)
    assert "summary_ms" in tb
    assert isinstance(tb["summary_ms"], int) and tb["summary_ms"] >= 5


def test_stage_timer_does_not_suppress_exceptions():
    tb: dict = {}
    try:
        with StageTimer(tb, "boom_ms"):
            raise ValueError("x")
    except ValueError:
        pass
    else:
        assert False, "exception should propagate"
    assert "boom_ms" in tb  # still recorded


def test_summarize_timing_accounts_and_surfaces_gap():
    tb = {"retrieve_ms": 100, "summary_ms": 300, "rerank_ms": 50, "route_total_ms": 600,
          "catalog_profile_cache_hit": True}
    summarize_timing(tb)
    assert tb["accounted_ms"] == 450          # 100+300+50 (ignores non-_ms + cache_hit)
    assert tb["unaccounted_ms"] == 150        # 600 - 450


def test_summarize_timing_no_total_is_safe():
    tb = {"retrieve_ms": 100}
    summarize_timing(tb)
    assert tb["accounted_ms"] == 100
    assert "unaccounted_ms" not in tb
