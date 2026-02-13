from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from src.app.rag.index import DocumentStore
from src.app.rag.guardrails import allow_doc, allow_query
from src.app.services.embeddings import SimpleEmbeddings


@dataclass
class RetrievedChunk:
    doc_id: str
    chunk_id: str
    text: str
    score: float
    meta: Dict[str, Any]


class Retriever:
    def __init__(self, store: Optional[DocumentStore] = None) -> None:
        self.store = store or DocumentStore()
        self.embedder = SimpleEmbeddings()

    def _chunk(self, text: str, max_len: int = 420) -> List[str]:
        chunks: List[str] = []
        buf: List[str] = []
        count = 0
        for para in (text or "").split("\n"):
            para = para.strip()
            if not para:
                continue
            if count + len(para) > max_len and buf:
                chunks.append(" ".join(buf))
                buf = []
                count = 0
            buf.append(para)
            count += len(para)
        if buf:
            chunks.append(" ".join(buf))
        return chunks

    def retrieve(self, query: str, k: int = 4, tenant_id: Optional[str] = None) -> List[RetrievedChunk]:
        if not allow_query(query):
            return []
        docs = self.store.list_documents()
        q_vec = self.embedder.embed_text(query)
        results: List[RetrievedChunk] = []
        for doc in docs:
            if not allow_doc(tenant_id, doc.tenant_allowlist):
                continue
            chunks = self._chunk(doc.content)
            for idx, chunk in enumerate(chunks):
                c_vec = self.embedder.embed_text(chunk)
                score = self.embedder.cosine(q_vec, c_vec)
                results.append(
                    RetrievedChunk(
                        doc_id=doc.doc_id,
                        chunk_id=f"{doc.doc_id}:{idx}",
                        text=chunk,
                        score=round(score, 4),
                        meta={"title": doc.title, "source": doc.source, "tags": doc.tags},
                    )
                )
        results.sort(key=lambda c: c.score, reverse=True)
        return results[:k]
