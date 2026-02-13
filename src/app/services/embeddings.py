from __future__ import annotations

import math
from typing import Dict, List
import os
import httpx


class SimpleEmbeddings:
    """Minimal bag-of-words embeddings with cosine similarity.

    Intended for lightweight demo use without external dependencies.
    """

    def tokenize(self, text: str) -> List[str]:
        return [t.lower() for t in (text or "").replace("\n", " ").split() if t.strip()]

    def embed_text(self, text: str) -> Dict[str, float]:
        tokens = self.tokenize(text)
        if not tokens:
            return {}
        freq: Dict[str, float] = {}
        for t in tokens:
            freq[t] = freq.get(t, 0.0) + 1.0
        # L2 normalize
        norm = math.sqrt(sum(v * v for v in freq.values())) or 1.0
        return {k: v / norm for k, v in freq.items()}

    def embed_product(self, name: str, specs: str | None = None) -> Dict[str, float]:
        return self.embed_text(f"{name or ''} {specs or ''}")

    def cosine(self, a: Dict[str, float], b: Dict[str, float]) -> float:
        if not a or not b:
            return 0.0
        keys = set(a) & set(b)
        return sum(a[k] * b[k] for k in keys)


class VectorStoreEmbeddings(SimpleEmbeddings):
    """Embeddings helper that indexes/query via a vector store (pgvector scaffold).

    Methods:
      - embed_text: returns a vector (list[float]) via simple bag-of-words if no external encoder
      - index(id, text): create embedding and index into vector store
      - query(embedding, top_k): query nearest vectors via vector store
    """

    def __init__(self):
        try:
            from src.app.services.vector_store import get_default_vector_store

            self.store = get_default_vector_store()
        except Exception:
            self.store = None

    def embed_text_vector(self, text: str) -> List[float]:
        provider = (os.getenv("EMBEDDINGS_PROVIDER") or "bow").strip().lower()
        if provider == "openai":
            try:
                api_key = os.getenv("OPENAI_API_KEY")
                base = os.getenv("OPENAI_API_BASE", "https://api.openai.com/v1")
                model = os.getenv("OPENAI_EMBEDDINGS_MODEL", "text-embedding-3-small")
                if not api_key:
                    raise RuntimeError("no_api_key")
                url = f"{base.rstrip('/')}/embeddings"
                payload = {"model": model, "input": text or ""}
                headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
                with httpx.Client(timeout=10.0) as client:
                    r = client.post(url, json=payload, headers=headers)
                    r.raise_for_status()
                    data = r.json()
                    arr = (data.get("data") or [{}])[0].get("embedding") or []
                    if isinstance(arr, list):
                        return [float(x) for x in arr]
            except Exception:
                # fallback to bow below
                pass
        # Default/fallback: convert bag-of-words dict into a dense vector using sorted tokens
        bag = self.embed_text(text)
        if not bag:
            return []
        keys = sorted(bag.keys())
        return [bag[k] for k in keys]

    def index(self, id: str, text: str, payload: Dict | None = None) -> Dict[str, any]:
        emb = self.embed_text_vector(text)
        if not self.store:
            return {"ok": False, "reason": "no_store"}
        return self.store.index(id, emb, payload)

    def query(self, text_or_embedding, top_k: int = 5) -> Dict[str, any]:
        if isinstance(text_or_embedding, str):
            emb = self.embed_text_vector(text_or_embedding)
        else:
            emb = text_or_embedding
        if not self.store:
            return {"ok": False, "reason": "no_store", "results": []}
        return self.store.query(emb, top_k=top_k)

