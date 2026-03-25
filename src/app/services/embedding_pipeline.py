from __future__ import annotations

from typing import Any, Dict, Iterable, List

from src.app.services.embeddings import VectorStoreEmbeddings
from src.app.services.vector_store import PgVectorStore, get_default_vector_store


class EmbeddingPipeline:
    """Small production-oriented wrapper for indexing/querying vectors."""

    def __init__(
        self,
        *,
        embedder: VectorStoreEmbeddings | None = None,
        store: PgVectorStore | None = None,
    ) -> None:
        self.embedder = embedder or VectorStoreEmbeddings()
        self.store = store or get_default_vector_store()

    def embed_text(self, text: str) -> List[float]:
        return list(self.embedder.embed_text_vector(text or ""))

    def index_documents(self, docs: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
        items: List[Dict[str, Any]] = []
        for doc in docs or []:
            doc_id = str(doc.get("id") or doc.get("product_id") or "").strip()
            source_text = str(doc.get("text") or doc.get("name") or "").strip()
            if not doc_id or not source_text:
                continue
            payload = dict(doc.get("payload") or {})
            if "sku" in doc and "sku" not in payload:
                payload["sku"] = doc.get("sku")
            items.append(
                {
                    "id": doc_id,
                    "embedding": self.embed_text(source_text),
                    "payload": payload,
                }
            )
        return self.store.batch_index(items)

    def query(self, text: str, *, top_k: int = 10, payload_filter: Dict[str, Any] | None = None) -> Dict[str, Any]:
        emb = self.embed_text(text)
        return self.store.query_with_filter(emb, top_k=top_k, payload_filter=payload_filter)
