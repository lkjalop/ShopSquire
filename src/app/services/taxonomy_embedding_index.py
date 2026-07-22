"""Taxonomy embedding index (V2 Phase 3.5→4 bridge) — semantic candidate generation.

The lexical candidate scorer requires a product's words to overlap a node's NAME — which is
structurally blind to 'Ibuprofen 200mg' → Pain Relief & Fever Reducers (zero shared tokens)
and weak on sibling discrimination (SSD vs Hard Drives). This index embeds every node's full
path once (pinned release, nomic-embed-text via local Ollama) so candidates come from MEANING;
the clamp/prior/earn-specificity rules downstream are unchanged — only candidate SOURCING
improves.

The index is a BUILD ARTIFACT, not a committed file (~45MB): build it with
    python scripts/build_taxonomy_embedding_index.py
and it lands next to the vendored release (data/taxonomy/shopify-<release>/embeddings.npz,
gitignored). Loading is cached; every failure path (missing index, Ollama down, dim mismatch)
degrades LOUDLY to lexical-only candidates — semantic sourcing is an upgrade, never a
dependency.
"""
from __future__ import annotations

import json
import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import List, Optional, Tuple

logger = logging.getLogger("shopsquire.taxonomy_embedding_index")

from src.app.services.taxonomy_registry import PINNED_RELEASE, _nodes  # noqa: E402

_INDEX_PATH = (Path(__file__).resolve().parents[3] / "data" / "taxonomy"
               / f"shopify-{PINNED_RELEASE}" / "embeddings.npz")
EMBED_MODEL = os.getenv("TAXONOMY_EMBED_MODEL", "nomic-embed-text")
_BATCH = 256


def _embed(texts: List[str], *, timeout: float = 120.0) -> Optional[List[List[float]]]:
    """Batch embed via Ollama /api/embed. None on ANY failure — callers degrade to lexical."""
    try:
        import httpx
        url = os.getenv("OLLAMA_URL", "http://localhost:11434").rstrip("/")
        r = httpx.post(
            f"{url}/api/embed",
            json={"model": EMBED_MODEL, "input": texts,
                  "keep_alive": os.getenv("OLLAMA_EMBED_KEEP_ALIVE", "60m")},
            timeout=timeout,
        )
        data = r.json() or {}
        if r.status_code != 200 or data.get("error"):
            logger.warning("embed call failed: http=%s error=%s", r.status_code,
                           str(data.get("error"))[:120])
            return None
        out = data.get("embeddings")
        return out if isinstance(out, list) and len(out) == len(texts) else None
    except Exception as exc:
        logger.warning("embed call failed: %s", repr(exc)[:120])
        return None


def build_index(*, path: Optional[Path] = None, batch: int = _BATCH) -> Optional[int]:
    """Embed every node's full path for the pinned release → npz {handles, vectors} (unit-
    normalized float32). Returns node count, None on failure. One-time (minutes)."""
    import numpy as np
    nodes = _nodes()
    handles = sorted(nodes)
    vectors: List[List[float]] = []
    import time
    for i in range(0, len(handles), batch):
        chunk = [nodes[h].full_path for h in handles[i:i + batch]]
        got = None
        for attempt in range(3):  # Ollama's embed runner can get evicted under GPU pressure
            got = _embed(chunk)   # mid-build (observed at 9,984/14,606) — retry with backoff
            if got is not None:
                break
            time.sleep(5 * (attempt + 1))
        if got is None:
            logger.error("index build aborted at %d/%d — embedder unavailable after retries",
                         i, len(handles))
            return None
        vectors.extend(got)
    arr = np.asarray(vectors, dtype="float32")
    arr /= (np.linalg.norm(arr, axis=1, keepdims=True) + 1e-9)
    out = path or _INDEX_PATH
    out.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(out, handles=np.array(handles), vectors=arr,
                        meta=np.array([json.dumps({"release": PINNED_RELEASE, "model": EMBED_MODEL})]))
    logger.info("taxonomy embedding index built: %d nodes -> %s", len(handles), out)
    return len(handles)


@lru_cache(maxsize=1)
def _load() -> Optional[tuple]:
    try:
        import numpy as np
        with np.load(_INDEX_PATH, allow_pickle=False) as z:
            handles = [str(h) for h in z["handles"]]
            vectors = z["vectors"]
            try:
                meta = json.loads(str(z["meta"][0]))
            except Exception:
                meta = {}
        if meta.get("release") not in (None, PINNED_RELEASE):
            logger.warning("embedding index is for release %s, pinned is %s — IGNORED (rebuild)",
                           meta.get("release"), PINNED_RELEASE)
            return None
        return handles, vectors
    except FileNotFoundError:
        return None
    except Exception as exc:
        logger.warning("embedding index unreadable: %s", repr(exc)[:120])
        return None


def index_available() -> bool:
    return _load() is not None


@lru_cache(maxsize=256)
def _semantic_top_k_cached(
    text: str,
    top_k: int,
    timeout: float,
) -> Optional[Tuple[Tuple[str, float], ...]]:
    """Cached query-side lookup for the immutable pinned taxonomy index."""
    loaded = _load()
    if loaded is None or not text:
        return None
    import numpy as np
    got = _embed([text[:512]], timeout=timeout)
    if got is None:
        return None
    q = np.asarray(got[0], dtype="float32")
    q /= (np.linalg.norm(q) + 1e-9)
    handles, vectors = loaded
    if vectors.shape[1] != q.shape[0]:
        logger.warning("embedding dim mismatch: index=%d query=%d — rebuild the index",
                       vectors.shape[1], q.shape[0])
        return None
    sims = vectors @ q
    top = np.argpartition(-sims, min(top_k, len(sims) - 1))[:top_k]
    ranked = sorted(((handles[i], float(sims[i])) for i in top), key=lambda p: -p[1])
    return tuple(ranked)


def semantic_top_k(text: str, *, top_k: int = 12) -> Optional[List[Tuple[str, float]]]:
    """Return semantic candidates without making repair an unbounded hot-path leg."""
    normalized = " ".join(str(text or "").strip().split()).lower()[:512]
    if not normalized:
        return None
    top_k = max(1, min(int(top_k or 12), 50))
    timeout = max(
        0.25,
        min(float(os.getenv("TAXONOMY_QUERY_EMBED_TIMEOUT_SEC", "2.0") or 2.0), 10.0),
    )
    result = _semantic_top_k_cached(normalized, top_k, timeout)
    return list(result) if result is not None else None
