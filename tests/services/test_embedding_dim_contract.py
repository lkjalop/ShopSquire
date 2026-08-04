"""Embedding dimension contract — vectors must match the pgvector vector(1536)
column so caption-RAG actually indexes (was variable-length BoW before)."""
from __future__ import annotations

from src.app.services.embeddings import VectorStoreEmbeddings, embedding_dim


def test_embed_text_vector_is_fixed_dim(monkeypatch):
    monkeypatch.delenv("EMBEDDINGS_PROVIDER", raising=False)  # BoW fallback path
    v = VectorStoreEmbeddings().embed_text_vector("MSI gaming laptop RTX 4070 16GB")
    assert embedding_dim() == 1536
    assert len(v) == 1536


def test_empty_input_still_valid_length_not_empty_list(monkeypatch):
    monkeypatch.delenv("EMBEDDINGS_PROVIDER", raising=False)
    v = VectorStoreEmbeddings().embed_text_vector("")
    assert isinstance(v, list) and len(v) == 1536  # not [] (which breaks the schema)


def test_fixed_dim_is_deterministic(monkeypatch):
    monkeypatch.delenv("EMBEDDINGS_PROVIDER", raising=False)
    a = VectorStoreEmbeddings().embed_text_vector("HP Victus 16 RTX 4060")
    b = VectorStoreEmbeddings().embed_text_vector("HP Victus 16 RTX 4060")
    assert a == b and len(a) == 1536


def test_upsert_rejects_wrong_dim(monkeypatch):
    # A wrong-length vector must be skipped (not crash the pgvector batch).
    seen = []
    import src.app.observability.metrics as m
    monkeypatch.setattr(m, "record_retrieval_source", lambda s, o: seen.append((s, o)))
    from src.app.repositories import embeddings as repo

    class _PgSession:
        class bind:
            class dialect:
                name = "postgresql"
        def execute(self, *a, **k):
            raise AssertionError("must not reach execute with wrong-dim vector")
        def commit(self):
            pass

    ok = repo.upsert_product_embedding(_PgSession(), "p1", [0.1, 0.2, 0.3])  # 3 != 1536
    assert ok is False
    assert ("product_embedding", "dim_mismatch") in seen
