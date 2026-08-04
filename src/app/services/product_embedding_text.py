"""Canonical product → embedding-text builder (single source of truth).

Every product embedding should be built from the SAME rich text so semantic search
is consistent. Before this, the ERP sync embedded the SKU string alone
(`erp/sync.py` — "richer text will be indexed elsewhere", which never happened),
making pgvector retrieval low-signal. This is that richer text:

    name. brand category. spec: value, ... . <VLM visual caption>

The VLM caption (Step B / build_visual_index --captions) is what makes this
*multimodal* RAG — the image's visual semantics ride the existing
`product_embeddings` table + HNSW index + `_SEARCH_EMBED_SQL` retrieval, with no
new vector store. `caption` is optional so the function is useful before captions
exist (text-only enrichment already beats SKU-only).

Pure + dependency-free → trivially unit-testable.
"""
from __future__ import annotations

import json
from typing import Any, Optional

_MAX_SPEC_FIELDS = 12


def _get(product: Any, *keys: str) -> Optional[Any]:
    for k in keys:
        v = product.get(k) if isinstance(product, dict) else getattr(product, k, None)
        if v not in (None, ""):
            return v
    return None


def _format_specs(specs: Any) -> str:
    if isinstance(specs, str):
        s = specs.strip()
        if not s:
            return ""
        try:
            specs = json.loads(s)
        except Exception:
            return s  # already a human string
    if not isinstance(specs, dict):
        return ""
    parts = []
    for k, v in specs.items():
        if v in (None, "", [], {}):
            continue
        if isinstance(v, bool):
            if not v:
                continue
            parts.append(str(k).replace("_", " "))
        else:
            parts.append(f"{str(k).replace('_', ' ')}: {v}")
    return ", ".join(parts[:_MAX_SPEC_FIELDS])


def build_embedding_text(product: Any, caption: Optional[str] = None) -> str:
    """Canonical embedding text for a product (dict or row/object).

    Falls back to SKU/id so the result is never empty — but with name/specs/caption
    present it is far richer than the legacy SKU-only embedding.
    """
    name = _get(product, "name", "title")
    brand = _get(product, "brand")
    category = _get(product, "category", "product_type")
    sku = _get(product, "sku", "id")
    specs = _get(product, "specs")

    segments = []
    if name:
        segments.append(str(name).strip())
    brand_cat = " ".join(str(x).strip() for x in (brand, category) if x).strip()
    if brand_cat:
        segments.append(brand_cat)
    spec_str = _format_specs(specs)
    if spec_str:
        segments.append(spec_str)
    if caption:
        segments.append(str(caption).strip())

    text = ". ".join(s for s in segments if s).strip()
    return text or (str(sku).strip() if sku else "")
