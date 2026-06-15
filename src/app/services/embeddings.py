from __future__ import annotations

import hashlib
import math
from typing import Any, Dict, List, Optional, Tuple
import os
import logging
import httpx

from src.app.security.provider_boundary import sanitize_for_provider

_log = logging.getLogger("shopsquire.embeddings")


def embedding_dim() -> int:
    """The product-embedding contract dimension. Must match the pgvector
    `product_embeddings` column (vector(1536)). Override with EMBEDDINGS_DIM."""
    try:
        return int(os.getenv("EMBEDDINGS_DIM", "1536") or 1536)
    except Exception:
        return 1536
try:
    import faiss  # type: ignore
    _HAS_FAISS = True
except Exception:
    faiss = None
    _HAS_FAISS = False


def _cosine_dense(a: List[float], b: List[float]) -> float:
    """Cosine similarity between two dense float vectors."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na < 1e-12 or nb < 1e-12:
        return 0.0
    return float(dot / (na * nb))


def cosine_dense(a: List[float], b: List[float]) -> float:
    return _cosine_dense(a, b)


def embed_text_ollama(
    text: str,
    *,
    model: str | None = None,
    base_url: str | None = None,
    timeout: float = 8.0,
) -> List[float]:
    """Embed *text* using a local Ollama embedding model (nomic-embed-text by default).

    Returns an empty list if Ollama is unavailable so callers can fall back to BoW.
    Environment variables:
        OLLAMA_BASE_URL   — Ollama server URL (default: http://localhost:11434)
        OLLAMA_EMBED_MODEL — model to use (default: nomic-embed-text)
    """
    base = (base_url or os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")).rstrip("/")
    mdl = model or os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")
    url = f"{base}/api/embeddings"
    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(url, json={"model": mdl, "prompt": text or ""})
            resp.raise_for_status()
            data = resp.json()
            emb = data.get("embedding") or []
            if isinstance(emb, list) and emb:
                return [float(v) for v in emb]
    except Exception as exc:
        _log.debug("Ollama embed_text failed (%s); falling back to BoW", exc)
    return []


def embed_text_openai(
    text: str,
    *,
    model: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
    timeout: float = 10.0,
) -> List[float]:
    """Embed *text* via OpenAI / compatible API. Returns [] on failure."""
    key = api_key or os.getenv("OPENAI_API_KEY", "")
    if not key:
        return []
    text, _, _ = sanitize_for_provider("openai", text, data_categories=["embedding_input"])
    base = (base_url or os.getenv("OPENAI_API_BASE", "https://api.openai.com/v1")).rstrip("/")
    mdl = model or os.getenv("OPENAI_EMBEDDINGS_MODEL", "text-embedding-3-small")
    url = f"{base}/embeddings"
    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(
                url,
                json={"model": mdl, "input": text or ""},
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            )
            resp.raise_for_status()
            data = resp.json()
            arr = (data.get("data") or [{}])[0].get("embedding") or []
            if isinstance(arr, list):
                return [float(x) for x in arr]
    except Exception as exc:
        _log.debug("OpenAI embed_text failed (%s); falling back to BoW", exc)
    return []


def embed_text_dense(text: str) -> Tuple[List[float], str]:
    """Return a dense embedding vector using the best available provider.

    Provider resolution order (controlled by EMBEDDINGS_PROVIDER env var):
        ollama    → calls local Ollama API (nomic-embed-text)
        openai    → calls OpenAI /v1/embeddings
        bow       → falls through to BoW (always available)
    Falls back to BoW when the selected provider is unavailable.

    Returns (vector, provider_name).
    """
    provider = (os.getenv("EMBEDDINGS_PROVIDER") or "bow").strip().lower()

    if provider in ("ollama",):
        vec = embed_text_ollama(text)
        if vec:
            return vec, "ollama"
        _log.debug("Ollama embedding unavailable; falling back to openai/bow")
        provider = "bow"

    if provider in ("openai",):
        vec = embed_text_openai(text)
        if vec:
            return vec, "openai"
        _log.debug("OpenAI embedding unavailable; falling back to bow")
        provider = "bow"

    # BoW fallback: project sparse TF dict into a dense vector via hash-bucket trick
    bag: Dict[str, float] = {}
    for token in (text or "").lower().split():
        bag[token] = bag.get(token, 0.0) + 1.0
    norm = math.sqrt(sum(v * v for v in bag.values())) or 1.0
    # Fixed 512-dim projection using FNV-like hash
    DIM = 512
    vec = [0.0] * DIM
    for tok, w in bag.items():
        idx = abs(hash(tok)) % DIM
        vec[idx] += w / norm
    vnorm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / vnorm for v in vec], "bow"


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
                text, _, _ = sanitize_for_provider("openai", text, data_categories=["embedding_input"])
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
        # Default/fallback: deterministic FIXED-DIMENSION vector via feature hashing.
        # The pgvector `product_embeddings` column is vector(EMBEDDINGS_DIM, default
        # 1536); a variable-length bag-of-words vector silently fails to index. Hash
        # each token into one of `dim` buckets (signed) and L2-normalize so every
        # vector is exactly `dim` long and unit-norm — matching the OpenAI path.
        dim = embedding_dim()
        bag = self.embed_text(text)
        vec = [0.0] * dim
        if not bag:
            return vec  # valid-length zero vector (never [] — that breaks the schema)
        for tok, weight in bag.items():
            h = int(hashlib.sha1(str(tok).encode("utf-8")).hexdigest(), 16)
            idx = h % dim
            sign = 1.0 if ((h >> 8) & 1) == 0 else -1.0
            vec[idx] += sign * float(weight)
        norm = math.sqrt(sum(x * x for x in vec)) or 1.0
        return [x / norm for x in vec]

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


def build_dense_text_index(items: List[Dict[str, Any]], *, text_key: str = "text") -> Dict[str, Any]:
    vectors: List[List[float]] = []
    kept: List[Dict[str, Any]] = []
    dim = 0
    provider = "bow"
    for it in items or []:
        text = str((it or {}).get(text_key) or "")
        vec, p = embed_text_dense(text)
        if not vec:
            continue
        provider = p
        if dim == 0:
            dim = len(vec)
        if len(vec) != dim:
            continue
        kept.append(it)
        vectors.append(vec)
    idx: Dict[str, Any] = {"items": kept, "vectors": vectors, "provider": provider, "dim": dim, "type": "dense_linear"}
    if _HAS_FAISS and vectors and dim > 0:
        try:
            import numpy as np  # type: ignore

            mat = np.array(vectors, dtype="float32")
            faiss.normalize_L2(mat)
            index = faiss.IndexFlatIP(dim)
            index.add(mat)
            idx["faiss"] = index
            idx["type"] = "faiss"
        except Exception:
            pass
    return idx


def query_dense_text_index(index: Dict[str, Any], *, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
    qvec, _ = embed_text_dense(query or "")
    if not qvec:
        return []
    k = max(1, int(top_k or 5))
    items = index.get("items") if isinstance(index.get("items"), list) else []
    vectors = index.get("vectors") if isinstance(index.get("vectors"), list) else []
    out: List[Dict[str, Any]] = []

    if index.get("type") == "faiss" and index.get("faiss") is not None:
        try:
            import numpy as np  # type: ignore

            q = np.array([qvec], dtype="float32")
            faiss.normalize_L2(q)
            scores, ids = index["faiss"].search(q, min(k, len(items)))
            for score, idx in zip(scores[0].tolist(), ids[0].tolist()):
                if idx < 0 or idx >= len(items):
                    continue
                out.append({"item": items[idx], "score": float(score)})
            return out
        except Exception:
            pass

    for i, vec in enumerate(vectors):
        if i >= len(items):
            break
        out.append({"item": items[i], "score": float(_cosine_dense(qvec, vec))})
    out.sort(key=lambda x: x.get("score", 0.0), reverse=True)
    return out[:k]

