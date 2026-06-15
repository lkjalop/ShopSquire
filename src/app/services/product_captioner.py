"""Step B — product visual captioner for multimodal RAG.

Produces a short natural-language caption of a product image to enrich the
embedding text (see product_embedding_text.build_embedding_text). It reuses the
ALREADY-cached `identify_product_from_image` (vision cache + bounded deadline)
and composes the caption from its STRUCTURED output — so there is no new
free-text JSON parsing (schema-safe by construction). Fail-open: returns "" on
any vision failure, so a caption outage never blocks indexing.

The caption itself is also cached under the 'caption' namespace so the batch
reindexer can re-run cheaply.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

_UNKNOWN = {"", "unknown", "none", "null", "integrated", "n/a"}


def _clean(v: Any) -> str:
    s = str(v or "").strip()
    return "" if s.lower() in _UNKNOWN else s


def compose_caption(identity: Optional[Dict[str, Any]]) -> str:
    """Compose a caption from a structured product-identity dict. Pure + testable."""
    if not isinstance(identity, dict) or not identity.get("identified"):
        return ""
    segs = []
    for k in ("brand", "model", "product_type"):
        c = _clean(identity.get(k))
        if c:
            segs.append(c)
    form = _clean(identity.get("form_factor"))
    if form:
        segs.append(form)
    gpu = _clean(identity.get("gpu_hint"))
    if gpu:
        segs.append(f"GPU {gpu}")
    disp = _clean(identity.get("display_inches_hint"))
    if disp:
        segs.append(f'{disp}" display')
    ram = _clean(identity.get("ram_gb_hint"))
    if ram:
        segs.append(f"{ram}GB RAM")
    return " ".join(segs).strip()


def caption_product(image_bytes: bytes, *, user_query: Optional[str] = None) -> str:
    """Cached visual caption for a product image. Fail-open ("")."""
    if not image_bytes:
        return ""
    _key = None
    try:
        from src.app.services import vision_cache as _vc
        _key = _vc.image_key(image_bytes, "caption")
        hit = _vc.get(_key)
        if isinstance(hit, str):
            return hit
    except Exception:
        _key = None

    caption = ""
    try:
        from src.app.services.product_identity_agent import identify_product_from_image
        identity = identify_product_from_image(image_bytes, user_query=user_query)
        caption = compose_caption(identity)
    except Exception:
        caption = ""

    if _key and caption:
        try:
            from src.app.services import vision_cache as _vc
            _vc.put(_key, caption)
        except Exception:
            pass
    return caption
