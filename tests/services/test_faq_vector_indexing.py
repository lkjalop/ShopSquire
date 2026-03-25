from scripts.index_catalog import run_index


def test_run_index_faq_ensures_table_and_indexes(monkeypatch):
    seen = {}

    monkeypatch.setattr(
        "src.app.services.vector_store.ensure_vector_table",
        lambda table_name, dim=1536: seen.setdefault("ensured", []).append((table_name, dim)),
    )

    class _FakePipeline:
        def __init__(self, store=None):
            self.store = store

        def index_documents(self, docs):
            seen["docs"] = list(docs)
            return {"ok": True, "indexed": len(seen["docs"]), "errors": 0}

    monkeypatch.setattr("src.app.services.embedding_pipeline.EmbeddingPipeline", _FakePipeline)

    out = run_index(index_catalog=False, index_faq=True, batch_size=10)

    assert ("faq_embeddings", 1536) in seen["ensured"]
    assert out["faq"]["indexed"] > 0
    assert all(str(item["id"]).startswith("faq:") for item in seen["docs"])
