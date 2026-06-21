"""Image visual-similarity stage (Tier 3). CORE / vertical-blind.

Given image bytes + the image<->query relationship + the image-feature allowlist verdict, produce
visual-similar product candidates as a LABELED source ("visual_similarity"). Only on_topic feeds
ranking (boost); adjacent gives a few safe hints; off_topic / gate-denied / no-index -> nothing.
visual_search.search returns [] when no FAISS index, so this is safe/inert until an index is built.
The image is DATA — OCR/QR/prompt text never reaches this stage.
"""
from __future__ import annotations

import time
from typing import Any, Callable, Dict, List, Optional

from src.app.services.commerce_source_status import SourceStatus
from src.app.services.image_query_relationship import ADJACENT, ON_TOPIC

_SOURCE = "visual_similarity"


def _default_search(**kw: Any) -> List[Dict[str, Any]]:
    from src.app.services.visual_search import search
    return search(**kw)


def run(
    *,
    image_bytes: Optional[bytes],
    query_text: Optional[str],
    relationship: Dict[str, Any],
    allow_visual: bool = True,
    budget_min: Optional[float] = None,
    budget_max: Optional[float] = None,
    search_fn: Optional[Callable[..., List[Dict[str, Any]]]] = None,
    k: int = 20,
) -> Dict[str, Any]:
    """Return {candidates, influence, source_status}. Never raises."""
    rel = (relationship or {}).get("relationship")
    influence = (relationship or {}).get("influence") or "none"
    if not allow_visual or rel not in (ON_TOPIC, ADJACENT) or not image_bytes:
        return {"candidates": [], "influence": "none",
                "source_status": SourceStatus(source=_SOURCE, status="empty").to_dict()}
    search_fn = search_fn or _default_search
    t0 = time.perf_counter()
    try:
        hits = search_fn(image_bytes=image_bytes, query_text=query_text, k=k,
                         budget_min=budget_min, budget_max=budget_max) or []
    except Exception as exc:
        return {"candidates": [], "influence": "none",
                "source_status": SourceStatus.errored(_SOURCE, str(exc), int((time.perf_counter() - t0) * 1000)).to_dict()}
    hits = [h for h in hits if isinstance(h, dict)]
    if rel == ADJACENT:
        hits = hits[:3]  # adjacent: a few safe hints only, never enough to dominate ranking
    for h in hits:
        h.setdefault("source", _SOURCE)
    return {"candidates": hits, "influence": influence,
            "source_status": SourceStatus.from_hits(_SOURCE, hits, int((time.perf_counter() - t0) * 1000)).to_dict()}
