"""Visual similarity search using CLIP embeddings and FAISS.

All ML dependencies (sentence-transformers, faiss-cpu) are **lazy-loaded**
so the platform starts without them.  When they're missing the module
gracefully degrades — ``search()`` returns an empty list and
``is_available()`` returns False.

Usage flow
----------
1. At startup or catalog refresh → ``build_index(products)``
2. At search time → ``search(image_bytes, budget_max=..., brand=...)``
3. The router blends visual-similarity results with text-based constraints.
"""
from __future__ import annotations

import io
import logging
import os
from typing import Any, Dict, List, Optional, Sequence

_log = logging.getLogger(__name__)

# ── Lazy-loaded globals ──────────────────────────────────────────
_clip_model: Any = None
_clip_processor: Any = None
_faiss_index: Any = None
_product_map: List[Dict[str, Any]] = []  # parallel array: index pos → product
_EMBED_DIM: int = 512
_MODEL_NAME = os.getenv("CLIP_MODEL_NAME", "sentence-transformers/clip-ViT-B-32")


def _load_clip():
    """Lazy-load CLIP model + processor.  Returns True on success."""
    global _clip_model, _clip_processor
    if _clip_model is not None:
        return True
    try:
        from sentence_transformers import SentenceTransformer  # type: ignore

        _clip_model = SentenceTransformer(_MODEL_NAME)
        _log.info("CLIP model loaded: %s", _MODEL_NAME)
        return True
    except Exception as exc:
        _log.warning("CLIP model unavailable (%s); visual search disabled.", exc)
        return False


def _get_faiss():
    try:
        import faiss  # type: ignore
        return faiss
    except ImportError:
        return None


def is_available() -> bool:
    """True when both CLIP and FAISS are importable."""
    return _load_clip() and _get_faiss() is not None


# ── Index management ─────────────────────────────────────────────

def build_index(products: Sequence[Dict[str, Any]]) -> int:
    """Build a FAISS index from product catalog images/descriptions.

    ``products`` items must have at least ``sku`` and either
    ``image_url`` (local file path or URL) or ``name``.
    Returns the number of items indexed.
    """
    global _faiss_index, _product_map, _EMBED_DIM

    if not _load_clip():
        return 0
    faiss = _get_faiss()
    if faiss is None:
        return 0

    import numpy as np

    texts: List[str] = []
    valid_products: List[Dict[str, Any]] = []

    for p in products:
        # Build a text representation for CLIP text embedding (cheaper than image for catalog)
        desc = f"{p.get('name', '')} {p.get('brand', '')} {' '.join(str(v) for v in (p.get('specs') or {}).values())}"
        texts.append(desc.strip() or p.get("sku", "unknown"))
        valid_products.append(p)

    if not texts:
        return 0

    embeddings = _clip_model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
    embeddings = np.asarray(embeddings, dtype="float32")
    _EMBED_DIM = embeddings.shape[1]

    index = faiss.IndexFlatIP(_EMBED_DIM)
    index.add(embeddings)

    _faiss_index = index
    _product_map = valid_products
    _log.info("Visual search index built: %d products, dim=%d", len(valid_products), _EMBED_DIM)
    return len(valid_products)


def search(
    image_bytes: bytes | None = None,
    query_text: str | None = None,
    k: int = 20,
    budget_max: float | None = None,
    budget_min: float | None = None,
    brand: str | None = None,
) -> List[Dict[str, Any]]:
    """Find top-k visually similar products, optionally filtered by budget/brand.

    Returns list of ``{sku, name, price_cents, score, ...}`` dicts.
    """
    if _faiss_index is None or _clip_model is None:
        return []
    faiss = _get_faiss()
    if faiss is None:
        return []

    import numpy as np

    embedding: Optional[np.ndarray] = None

    if image_bytes:
        try:
            from PIL import Image  # type: ignore

            img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
            embedding = _clip_model.encode(img, normalize_embeddings=True)
        except Exception as exc:
            _log.warning("CLIP image encode failed: %s", exc)

    if embedding is None and query_text:
        embedding = _clip_model.encode(query_text, normalize_embeddings=True)

    if embedding is None:
        return []

    query_vec = np.asarray([embedding], dtype="float32")
    # Over-fetch so we can post-filter by budget/brand
    fetch_k = min(k * 5, _faiss_index.ntotal)
    scores, indices = _faiss_index.search(query_vec, fetch_k)

    results: List[Dict[str, Any]] = []
    for rank, (score, idx) in enumerate(zip(scores[0], indices[0])):
        if idx < 0 or idx >= len(_product_map):
            continue
        p = _product_map[idx]
        price = p.get("price_cents") or 0
        # Budget filter
        if budget_max is not None and price > budget_max * 100:
            continue
        if budget_min is not None and price < budget_min * 100:
            continue
        # Brand filter
        if brand and str(p.get("brand", "")).lower() != brand.lower():
            continue
        results.append({
            **p,
            "visual_score": round(float(score), 4),
            "visual_rank": rank,
        })
        if len(results) >= k:
            break

    return results
