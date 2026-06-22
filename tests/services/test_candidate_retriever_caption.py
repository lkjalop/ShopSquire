"""Step D/E — caption (multimodal-RAG) retrieval source + 3-way RRF + observability."""
from __future__ import annotations

import src.app.services.candidate_retriever as cr


def test_merge_rrf_three_way_boosts_cross_list_item():
    a = [{"sku": "X"}, {"sku": "Y"}]
    b = [{"sku": "Y"}, {"sku": "Z"}]
    c = [{"sku": "Y"}]
    out = cr.merge_rrf(a, b, c, top_n=10)
    skus = [r["sku"] for r in out]
    assert skus[0] == "Y"          # in all three lists → highest RRF
    assert set(skus) == {"X", "Y", "Z"}


def test_from_caption_fail_open_and_observable(monkeypatch):
    # No pgvector index in the test DB → must return [] without crashing, and the
    # empty outcome must be observable (not silent).
    seen = []
    import src.app.observability.metrics as m
    monkeypatch.setattr(m, "record_retrieval_source", lambda s, o: seen.append((s, o)))
    out = cr.from_caption("gaming laptop with RTX 4070", top_k=5)
    assert out == []
    assert any(s == "caption" for s, _ in seen)


def test_from_caption_maps_search_hits(monkeypatch):
    # Mock embedding + the pgvector search + product rows to prove mapping + scoring.
    import src.app.services.embeddings as emb_mod
    monkeypatch.setattr(emb_mod, "VectorStoreEmbeddings",
                        lambda *a, **k: type("E", (), {"embed_text_vector": lambda self, t: [0.1, 0.2, 0.3]})())
    import src.app.repositories.embeddings as repo
    monkeypatch.setattr(repo, "search_products_by_embedding",
                        lambda db, emb, top_k=5, **k: [{"product_id": "p1", "distance": 0.2}])

    class _FakeDB:
        def execute(self, *a, **k):
            class _R:
                def fetchall(self_inner):
                    return [("p1", "GAM-1", "MSI Katana 15", "MSI", 149900, "", {"gpu": "RTX 4070"})]
            return _R()

    import contextlib
    @contextlib.contextmanager
    def _fake_session():
        yield _FakeDB()
    monkeypatch.setattr(cr, "db_session", _fake_session)

    out = cr.from_caption("gaming laptop", top_k=5)
    assert len(out) == 1
    assert out[0]["sku"] == "GAM-1" and out[0]["_source"] == "caption"
    assert out[0]["score"] == round(1.0 - 0.2, 6)


def test_retrieve_and_merge_three_sources_no_crash():
    out = cr.retrieve_and_merge("gaming laptop", top_n=5)
    assert isinstance(out, list)


def _capture_db(monkeypatch):
    """Patch cr.db_session to capture the SQL + params from_db builds (no real DB)."""
    captured: dict = {}

    class _FakeDB:
        def execute(self, sql, params=None):
            captured["sql"] = str(sql)
            captured["params"] = params or {}
            class _R:
                def fetchall(self_inner):
                    return []
            return _R()

    import contextlib

    @contextlib.contextmanager
    def _fake_session():
        yield _FakeDB()

    monkeypatch.setattr(cr, "db_session", _fake_session)
    return captured


def test_from_db_tokenises_multiword_query(monkeypatch):
    # The bug: a realistic multi-word query was matched as LIKE %whole phrase% and hit no
    # product → the scatter-gather DB leg returned 0. Now each significant token is its own
    # OR'd LIKE term, so recall is restored.
    captured = _capture_db(monkeypatch)
    cr.from_db("show me a gaming laptop $1500-2100")
    params = captured["params"]
    assert "qt" not in params  # no single whole-phrase term
    vals = {v for k, v in params.items() if k.startswith("qt_")}
    assert "%gaming%" in vals and "%laptop%" in vals
    assert "%show%" not in vals and "%me%" not in vals     # filler/short dropped
    assert not any("gaming laptop" in v for v in vals)     # never the raw phrase as one term


def test_from_db_all_filler_query_does_not_force_zero(monkeypatch):
    # A query that is only filler/short tokens adds NO keyword condition → returns the active
    # catalog as a candidate pool rather than being forced to 0 results.
    captured = _capture_db(monkeypatch)
    cr.from_db("show me the")
    assert not any(str(k).startswith("qt") for k in captured["params"])
