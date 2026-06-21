"""Image <-> query relationship classifier (Tier 3 / safe multimodal). CORE / vertical-blind.

Decides how much an uploaded image may influence retrieval, using the ACTIVE profile's category
detection (injected) + companion map (profile upsell_companions). The image is treated as DATA:
OCR/QR/prompt text never reaches this classifier — only safe labels + the detected product type.

  on_topic : image product type == query product type        -> may BOOST ranking
  adjacent : image is a companion type of the query (or v.v.) -> safe HINTS only, never overrides text
  off_topic: unrelated / contradictory / no signal / suspicious -> trace/security only, no ranking
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

ON_TOPIC = "on_topic"
ADJACENT = "adjacent"
OFF_TOPIC = "off_topic"


def _companions(ptype: str, companions_map: Optional[Dict[str, List[str]]]) -> set:
    return {str(x).strip().lower() for x in (companions_map or {}).get(ptype, []) if str(x).strip()}


def classify(
    *,
    image_labels: Optional[List[str]],
    query: Optional[str],
    image_suspicious: bool = False,
    detect_category: Optional[Callable[..., str]] = None,
    companions_map: Optional[Dict[str, List[str]]] = None,
) -> Dict[str, Any]:
    """Return {relationship, reason, image_type, query_type, influence}.

    `detect_category(query=..., image_labels=...) -> slug` is injected (category_router.detect_category)
    so this stays profile-backed + testable. `companions_map` = profile upsell_companions.
    influence: 'boost' (on_topic) | 'hint' (adjacent) | 'none' (off_topic).
    """
    if image_suspicious:
        return {"relationship": OFF_TOPIC, "reason": "suspicious_image", "image_type": None,
                "query_type": None, "influence": "none"}
    labels = [str(x) for x in (image_labels or []) if str(x).strip()]
    if not labels:
        return {"relationship": OFF_TOPIC, "reason": "no_image_signal", "image_type": None,
                "query_type": None, "influence": "none"}

    img_type = str((detect_category(image_labels=labels) if detect_category else "") or "").strip().lower()
    q_type = str((detect_category(query=query) if detect_category else "") or "").strip().lower()

    if img_type and q_type and img_type == q_type:
        return {"relationship": ON_TOPIC, "reason": "same_product_type", "image_type": img_type,
                "query_type": q_type, "influence": "boost"}
    if img_type and q_type and (img_type in _companions(q_type, companions_map)
                                or q_type in _companions(img_type, companions_map)):
        return {"relationship": ADJACENT, "reason": "companion_product_type", "image_type": img_type,
                "query_type": q_type, "influence": "hint"}
    return {"relationship": OFF_TOPIC, "reason": "unrelated_product_type", "image_type": img_type or None,
            "query_type": q_type or None, "influence": "none"}
