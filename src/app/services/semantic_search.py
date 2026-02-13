from __future__ import annotations

from typing import Dict, List
from src.app.services.embeddings import SimpleEmbeddings, VectorStoreEmbeddings
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
