"""Honest readiness for the flag-gated commerce features (visual similarity + external search).

A feature is LIVE only when all preconditions hold — flag + (index | endpoint+allowlist). The
readiness report tells the truth so we never claim a capability that won't produce results.
"""
from __future__ import annotations

from src.app.services.commerce_feature_readiness import (
    external_search_readiness,
    visual_search_readiness,
)


# ── visual similarity ──
def test_visual_off_when_flag_off(monkeypatch):
    monkeypatch.delenv("IMAGE_SIMILARITY_ENABLED", raising=False)
    r = visual_search_readiness({"IMAGE_SIMILARITY_ENABLED": False},
                                status_fn=lambda: {"index_ready": True, "available": True, "index_size": 9})
    assert r["live"] is False and "off" in r["reason"]


def test_visual_enabled_but_no_index_is_not_live(monkeypatch):
    monkeypatch.setenv("IMAGE_SIMILARITY_ENABLED", "1")
    r = visual_search_readiness({}, status_fn=lambda: {"index_ready": False, "available": True})
    assert r["live"] is False and "index" in r["reason"].lower()


def test_visual_live_when_flag_and_index(monkeypatch):
    monkeypatch.setenv("IMAGE_SIMILARITY_ENABLED", "1")
    r = visual_search_readiness({}, status_fn=lambda: {"index_ready": True, "available": True, "index_size": 42})
    assert r["live"] is True and r["index_size"] == 42 and r["reason"] == "live"


def test_visual_reports_missing_deps(monkeypatch):
    monkeypatch.setenv("IMAGE_SIMILARITY_ENABLED", "1")
    r = visual_search_readiness({}, status_fn=lambda: {"index_ready": False, "available": False})
    assert r["live"] is False and ("CLIP" in r["reason"] or "FAISS" in r["reason"])


# ── external search ──
def test_external_off_when_flag_off(monkeypatch):
    monkeypatch.delenv("EXTERNAL_RESEARCH_ENABLED", raising=False)
    monkeypatch.delenv("EXTERNAL_RESEARCH_SEARCH_URL", raising=False)
    r = external_search_readiness({"EXTERNAL_RESEARCH_ENABLED": False})
    assert r["live"] is False and "off" in r["reason"]


def test_external_enabled_but_no_endpoint(monkeypatch):
    monkeypatch.setenv("EXTERNAL_RESEARCH_ENABLED", "1")
    monkeypatch.delenv("EXTERNAL_RESEARCH_SEARCH_URL", raising=False)
    r = external_search_readiness({}, allowlist=["trusted.com"])
    assert r["live"] is False and "SEARCH_URL" in r["reason"]


def test_external_enabled_endpoint_but_no_allowlist(monkeypatch):
    monkeypatch.setenv("EXTERNAL_RESEARCH_ENABLED", "1")
    monkeypatch.setenv("EXTERNAL_RESEARCH_SEARCH_URL", "https://search.example.com/api?q={query}")
    r = external_search_readiness({}, allowlist=[])
    assert r["live"] is False and "allowlist" in r["reason"].lower()


def test_external_live_when_all_present(monkeypatch):
    monkeypatch.setenv("EXTERNAL_RESEARCH_ENABLED", "1")
    monkeypatch.setenv("EXTERNAL_RESEARCH_SEARCH_URL", "https://search.example.com/api?q={query}")
    r = external_search_readiness({}, allowlist=["trusted.com", "techradar.com"])
    assert r["live"] is True and r["allowlist_size"] == 2 and r["reason"] == "live"
