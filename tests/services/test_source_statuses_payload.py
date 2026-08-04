"""Item 1 — /suggest surfaces per-source retrieval status for the trace panel."""
from __future__ import annotations

from src.app.services.recommendation_response_contract import build_source_statuses


def test_full_source_status_shape():
    s = build_source_statuses([{"sku": "a"}, {"sku": "b"}], {"retrieve_ms": 42})
    assert isinstance(s, list) and len(s) == 1
    row = s[0]
    assert row["source"] == "catalog_db"
    assert row["status"] == "full"
    assert row["hit_count"] == 2
    assert row["latency_ms"] == 42


def test_empty_source_status():
    s = build_source_statuses([], {"retrieve_ms": 7})
    assert s[0]["status"] == "empty" and s[0]["hit_count"] == 0


def test_never_raises_on_bad_input():
    assert build_source_statuses(None, None) == [] or isinstance(build_source_statuses(None, None), list)
