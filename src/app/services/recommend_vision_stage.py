"""Vision decision stage — extracted from recommend.py::suggest() (core/adapter split, P2).

The first slice of the vision stage: the PURE vision/brand DECISION primitives —
  • cross-modal (vision ⟂ NLP) brand-conflict detection → clarifying question, and
  • resolving a SUPPORTED brand hint from text/constraints/query.
These decide how an image's brand signal interacts with the text request; they are pure (no DB, no
request locals) and depend only on already-extracted modules (recommend_utils for brand display,
recommend_image_hints for the supported-brand set) — so no circular import back to the router.

The larger inline vision ORCHESTRATION (image ingest → feature gate → grounding → catalog
relevance) remains in suggest() pending a dedicated RecommendStageState pass; this module is where
those pure decisions land as they are peeled off.

ADAPTER (flavour): the supported-brand list inside _resolve_supported_brand_hint is electronics
flavour (Phase-2 profile-back target) — so this module is intentionally NOT yet on the
no-flavour-in-core lint, like recommend_image_hints.py / recommend_utils.py.
"""
from __future__ import annotations

from typing import Any

from src.app.services.recommend_utils import _brand_display_name
from src.app.services.recommend_image_hints import _SUPPORTED_IMAGE_BRAND_HINTS


def _cross_modal_brand_conflict_question(
    text_brands: Any, image_brand: str | None
) -> tuple[str | None, dict | None]:
    """Vision ⟂ NLP consistency check: the buyer's TEXT brand differs from the brand
    the uploaded IMAGE looks like ("show me Asus" + an MSI photo).

    Returns (mismatch_note, clarifying_question) or (None, None). Pure + testable.
    Policy: never auto-switch — keep the STATED (text) brand and ASK. The mismatch is
    both a UX signal (wrong photo grabbed) and a weak manipulation signal (a mismatched
    image can be an attempt to steer brand routing), so it is also trace-logged."""
    try:
        tb = [str(b).lower() for b in (text_brands or []) if str(b).strip()]
        ib = str(image_brand or "").lower()
        if not ib or not tb or ib in tb:
            return None, None
        img_disp = _brand_display_name(ib)
        txt_disp = _brand_display_name(tb[0])
        note = (
            f"You asked for {txt_disp}, but the uploaded image looks like a {img_disp}. "
            f"I've kept your {txt_disp} request — let me know if you'd rather match the image."
        )
        question = {
            "id": "ask_image_text_brand_conflict",
            "text": (
                f"Quick check: your text says {txt_disp} but the photo looks like {img_disp}. "
                f"Which should I match?"
            ),
            "options": [
                {"id": "conflict_keep_text", "label": f"Keep my {txt_disp} request"},
                {"id": "conflict_use_image", "label": f"Actually, match the image ({img_disp})"},
                {"id": "conflict_compare", "label": f"Compare {txt_disp} vs {img_disp}"},
            ],
            "priority": 0,
            "source": "image_text_brand_conflict",
        }
        return note, question
    except Exception:
        return None, None


def _supported_brands() -> set:
    """Brands the ACTIVE vertical recognises — the StoreProfile `manufacturers` keys
    (prefer-profile: pharmacy → panadol/nurofen…, fashion → nike/adidas…), falling back to the
    inline electronics set only if the profile carries no manufacturers."""
    try:
        from src.app.platform.store_profile import brand_label_patterns
        prof = {str(k).strip().lower() for k in (brand_label_patterns() or {}).keys()}
        if prof:
            return prof
    except Exception:
        pass
    return set(_SUPPORTED_IMAGE_BRAND_HINTS)


def _resolve_supported_brand_hint(
    explicit: str | None,
    constraints: dict | None = None,
    query_text: str | None = None,
) -> str:
    supported = _supported_brands()
    direct = str(explicit or "").strip().lower()
    if direct in supported:
        return direct
    c = constraints if isinstance(constraints, dict) else {}
    for key in ("_request_brand_hint", "_inferred_image_brand"):
        val = str(c.get(key) or "").strip().lower()
        if val in supported:
            return val
    for raw in (c.get("brands") or []):
        val = str(raw or "").strip().lower()
        if val in supported:
            return val
    q = str(query_text or "").lower()
    # Profile-driven query-token resolution: a brand/line/alias token maps to its manufacturer when
    # supported (electronics macbook→apple, vivobook→asus; pharmacy panadol→panadol; fashion
    # "air max"→nike). No hardcoded brand list — the active StoreProfile is the source of truth.
    try:
        from src.app.platform.store_profile import product_line_index
        for token, spec in (product_line_index() or {}).items():
            if token and token in q:
                mfr = str((spec or {}).get("manufacturer") or "").strip().lower()
                if mfr in supported:
                    return mfr
    except Exception:
        pass
    for brand in supported:
        if brand and brand in q:
            return brand
    return ""
