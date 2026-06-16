"""1.2 — typed SourceStatus: full/empty/error per retrieval leg + degradation ledger."""
from __future__ import annotations

import src.app.services.candidate_retriever as cr
from src.app.services.commerce_source_status import SourceStatus, degraded_sources, FULL, EMPTY, ERROR


def test_status_classifies_full_empty_error(monkeypatch):
    monkeypatch.setattr(cr, "from_db", lambda *a, **k: [{"sku": "A", "name": "A", "price_cents": 100}])
    monkeypatch.setattr(cr, "from_vector", lambda *a, **k: [])           # empty
    def _boom(*a, **k):
        raise RuntimeError("vector dimension mismatch")
    monkeypatch.setattr(cr, "from_caption", _boom)                       # error
    monkeypatch.setattr(cr, "apply_inventory_filter", lambda c, **k: c)

    cands, statuses = cr.retrieve_with_statuses("gaming laptop", top_n=5)
    assert statuses["catalog_db"].status == FULL
    assert statuses["clip_visual"].status == EMPTY
    assert statuses["caption_rag"].status == ERROR
    assert statuses["caption_rag"].error and "dimension" in statuses["caption_rag"].error
    # full leg still yields candidates
    assert any(c.get("sku") == "A" for c in cands)


def test_degraded_sources_ledger(monkeypatch):
    monkeypatch.setattr(cr, "from_db", lambda *a, **k: [])
    monkeypatch.setattr(cr, "from_vector", lambda *a, **k: [])
    def _boom(*a, **k):
        raise RuntimeError("index unavailable")
    monkeypatch.setattr(cr, "from_caption", _boom)
    monkeypatch.setattr(cr, "apply_inventory_filter", lambda c, **k: c)

    _cands, statuses = cr.retrieve_with_statuses("x")
    ledger = degraded_sources(statuses)
    # only the errored source is in the degradation ledger (empty is not "degraded")
    assert [d["source"] for d in ledger] == ["caption_rag"]


def test_status_has_latency_and_dict():
    s = SourceStatus.from_hits("catalog_db", [{"sku": "x"}], 42)
    d = s.to_dict()
    assert d["status"] == FULL and d["hit_count"] == 1 and d["latency_ms"] == 42
    assert s.safe_for_buyer is True
