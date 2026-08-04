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


def run_image_relationship_stage(
    *,
    image_context: Dict[str, Any],
    query: Any,
    image_feature_allowlist: Any,
    image_reupload_reasons: Any,
    image_similarity_enabled: bool,
    decode_image_blob: Callable[..., Any],
    kv: Any = None,
    budget_min: Any = None,
    budget_max: Any = None,
    classify_fn: Optional[Callable[..., Any]] = None,
    detect_category_fn: Optional[Callable[..., Any]] = None,
    companions_map: Optional[Dict[str, Any]] = None,
    visual_run_fn: Optional[Callable[..., Any]] = None,
) -> Dict[str, Any]:
    """Tier-3 safe multimodal stage: classify the image<->query relationship (ALWAYS, for
    observability) and — only when image_similarity_enabled — run the labeled visual leg.

    Returns {image_relationship, [visual_similarity], [visual_similarity_status]} for the caller to
    attach to the payload. OCR/QR/prompt text NEVER reaches this — only safe labels + the detected
    product type; a gate-denied/suspicious image is marked suspicious (-> off_topic, no influence).
    decode_image_blob is injected (route-local); classify/detect/visual are injected with lazy
    defaults for testability. Raises on internal error so the caller can trace it."""
    out: Dict[str, Any] = {}
    if classify_fn is None:
        from src.app.services.image_query_relationship import classify as classify_fn
    if detect_category_fn is None:
        from src.app.services.category_router import detect_category as detect_category_fn
    if companions_map is None:
        try:
            from src.app.platform.store_profile import profile_slot
            companions_map = profile_slot("upsell_companions", default={}) or {}
        except Exception:
            companions_map = {}

    allowed = (
        getattr(image_feature_allowlist, "allow_image_labels", True)
        and getattr(image_feature_allowlist, "verdict", "full") != "text_only"
    )
    rel = classify_fn(
        image_labels=image_context.get("labels") or [],
        query=query,
        image_suspicious=(not allowed) or bool(image_reupload_reasons),
        detect_category=detect_category_fn,
        companions_map=companions_map,
    )
    out["image_relationship"] = rel

    if image_similarity_enabled:
        if visual_run_fn is None:
            visual_run_fn = run  # the module-local visual-similarity stage
        vis = visual_run_fn(
            image_bytes=decode_image_blob(kv if isinstance(kv, dict) else {}, image_context.get("hash")),
            query_text=query, relationship=rel, allow_visual=allowed,
            budget_min=budget_min, budget_max=budget_max,
        )
        out["visual_similarity"] = vis.get("candidates") or []
        out["visual_similarity_status"] = vis.get("source_status")
    return out
