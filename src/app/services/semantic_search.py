from __future__ import annotations

from typing import Any, Dict, List
from src.app.services.embeddings import (
    SimpleEmbeddings,
    VectorStoreEmbeddings,
    build_dense_text_index,
    query_dense_text_index,
)
import os

class SemanticService:
    """Lightweight semantic wrapper around the existing SimpleEmbeddings.

    Provides a single place to swap-in higher-quality embedding models later.
    """

    def __init__(self):
        provider = (os.getenv("EMBEDDINGS_PROVIDER") or "bow").strip().lower()
        # When configured for vector store/openai, use the VectorStoreEmbeddings wrapper (still tolerates bow fallback)
        if provider in ("openai", "vector", "pgvector"):
            try:
                self._impl = VectorStoreEmbeddings()
            except Exception:
                self._impl = SimpleEmbeddings()
        else:
            self._impl = SimpleEmbeddings()

    def embed_text(self, text: str) -> Dict[str, float]:
        return self._impl.embed_text(text)

    def embed_product(self, name: str, specs: str | None = None) -> Dict[str, float]:
        return self._impl.embed_product(name, specs)

    def cosine(self, a: Dict[str, float], b: Dict[str, float]) -> float:
        return self._impl.cosine(a, b)

    def tokenize(self, text: str) -> List[str]:
        return self._impl.tokenize(text)


def semantic_retrieve_text_chunks(
    *,
    query: str,
    chunks: List[Dict[str, Any]],
    text_key: str = "text",
    top_k: int = 8,
    min_score: float = 0.08,
) -> List[Dict[str, Any]]:
    """Dense semantic retrieval for short text chunks with FAISS fallback."""
    if not query or not isinstance(chunks, list) or not chunks:
        return []
    idx = build_dense_text_index(chunks, text_key=text_key)
    ranked = query_dense_text_index(idx, query=query, top_k=top_k)
    out: List[Dict[str, Any]] = []
    for row in ranked:
        score = float(row.get("score") or 0.0)
        if score < float(min_score):
            continue
        item = row.get("item") if isinstance(row.get("item"), dict) else {}
        out.append({"item": item, "score": score})
    return out
