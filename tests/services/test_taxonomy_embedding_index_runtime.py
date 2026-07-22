from src.app.services import taxonomy_embedding_index as index


def test_semantic_query_is_cached_and_uses_bounded_timeout(monkeypatch):
    calls = []

    class _Vectors:
        shape = (1, 2)

        def __matmul__(self, _query):
            import numpy as np
            return np.asarray([0.9], dtype="float32")

    monkeypatch.setattr(index, "_load", lambda: (["el-6-6"], _Vectors()))

    def _embed(texts, *, timeout):
        calls.append((texts, timeout))
        return [[1.0, 0.0]]

    monkeypatch.setattr(index, "_embed", _embed)
    monkeypatch.setenv("TAXONOMY_QUERY_EMBED_TIMEOUT_SEC", "1.25")
    index._semantic_top_k_cached.cache_clear()

    first = index.semantic_top_k("  Forklifts  ", top_k=8)
    second = index.semantic_top_k("forklifts", top_k=8)

    assert first == second
    assert first and first[0][0] == "el-6-6"
    assert calls == [(["forklifts"], 1.25)]
