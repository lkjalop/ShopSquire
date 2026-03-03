"""Image Intent Router Agent — classifies image uploads into visual_search or cv_triage.

Uses a multi-signal decision matrix combining:
- Image analysis signals (damage score, labels, OCR)
- User query text (explicit intent keywords)
- Conversation context (last N messages for implicit intent)
- Cached image context from session

Outputs: {intent, confidence, reason, signals}
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Intent keyword patterns
# ---------------------------------------------------------------------------
_VISUAL_SEARCH_PAT = re.compile(
    r"\b(find similar|similar product|like this|shop|buy|purchase|look for|"
    r"visual search|where can i|price check|alternatives|same model|"
    r"show me|search for|recommend)\b",
    re.IGNORECASE,
)

_CV_TRIAGE_PAT = re.compile(
    r"\b(return|broken|damaged|refund|complaint|defective|wrong item|"
    r"warranty|repair|replace|missing part|not working|dead pixel|"
    r"cracked|shattered|dent|scratch|issue|problem|faulty|"
    r"rma|exchange|claim)\b",
    re.IGNORECASE,
)

_FAQ_PAT = re.compile(
    r"\b(how do i|shipping|delivery|tracking|eta|when will|"
    r"cancel order|return policy|warranty policy|help)\b",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Damage severity thresholds
# ---------------------------------------------------------------------------
HIGH_DAMAGE_THRESHOLD = 0.7
MEDIUM_DAMAGE_THRESHOLD = 0.4
AUTO_ROUTE_CONFIDENCE = 0.85
DISAMBIGUATE_THRESHOLD = 0.55


def classify_image_intent(
    *,
    image_labels: Optional[List[str]] = None,
    image_ocr_text: Optional[str] = None,
    damage_score: float = 0.0,
    is_product_photo: bool = False,
    user_query: Optional[str] = None,
    recent_messages: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Classify what the user wants to do with an uploaded image.

    Returns
    -------
    dict with keys:
        intent: "visual_search" | "cv_triage" | "faq" | "disambiguate"
        confidence: float 0-1
        reason: str
        signals: dict of contributing signals
    """
    signals: Dict[str, Any] = {}
    scores: Dict[str, float] = {"visual_search": 0.0, "cv_triage": 0.0, "faq": 0.0}

    query = (user_query or "").strip()
    labels = image_labels or []
    ocr = (image_ocr_text or "").strip()

    # -----------------------------------------------------------------------
    # Signal 1: Explicit intent in user query text
    # -----------------------------------------------------------------------
    if query:
        if _VISUAL_SEARCH_PAT.search(query):
            scores["visual_search"] += 0.45
            signals["query_visual_search"] = True
        if _CV_TRIAGE_PAT.search(query):
            scores["cv_triage"] += 0.45
            signals["query_cv_triage"] = True
        if _FAQ_PAT.search(query):
            scores["faq"] += 0.35
            signals["query_faq"] = True

    # -----------------------------------------------------------------------
    # Signal 2: Damage score from CV triage
    # -----------------------------------------------------------------------
    if damage_score >= HIGH_DAMAGE_THRESHOLD:
        scores["cv_triage"] += 0.35
        signals["high_damage"] = True
        signals["damage_score"] = damage_score
    elif damage_score >= MEDIUM_DAMAGE_THRESHOLD:
        scores["cv_triage"] += 0.20
        signals["medium_damage"] = True
        signals["damage_score"] = damage_score
    else:
        scores["visual_search"] += 0.15
        signals["low_damage"] = True
        signals["damage_score"] = damage_score

    # -----------------------------------------------------------------------
    # Signal 3: Product photo heuristic (clean image, single object)
    # -----------------------------------------------------------------------
    if is_product_photo:
        scores["visual_search"] += 0.20
        signals["is_product_photo"] = True

    # -----------------------------------------------------------------------
    # Signal 4: Labels indicating damage vs product
    # -----------------------------------------------------------------------
    label_text = " ".join(labels).lower()
    damage_label_kw = ["crack", "broken", "dent", "scratch", "shatter", "damage", "defect"]
    product_label_kw = ["laptop", "phone", "tablet", "monitor", "keyboard", "headphone",
                        "camera", "printer", "router", "speaker", "watch", "console"]
    if any(kw in label_text for kw in damage_label_kw):
        scores["cv_triage"] += 0.15
        signals["damage_labels"] = True
    if any(kw in label_text for kw in product_label_kw):
        scores["visual_search"] += 0.10
        signals["product_labels"] = True

    # -----------------------------------------------------------------------
    # Signal 5: Conversation context (last 3 messages)
    # -----------------------------------------------------------------------
    if recent_messages:
        recent_text = " ".join(
            str(m.get("content") or "") for m in (recent_messages or [])[-3:]
        ).lower()
        if _CV_TRIAGE_PAT.search(recent_text):
            scores["cv_triage"] += 0.15
            signals["context_complaint"] = True
        if _VISUAL_SEARCH_PAT.search(recent_text):
            scores["visual_search"] += 0.10
            signals["context_visual"] = True

    # -----------------------------------------------------------------------
    # Signal 6: No text at all with image → bias toward visual search if clean
    # -----------------------------------------------------------------------
    if not query and damage_score < MEDIUM_DAMAGE_THRESHOLD:
        scores["visual_search"] += 0.10
        signals["no_text_clean_image"] = True

    # -----------------------------------------------------------------------
    # Decide
    # -----------------------------------------------------------------------
    best_intent = max(scores, key=scores.get)  # type: ignore[arg-type]
    best_score = scores[best_intent]

    # Normalize confidence to 0-1
    total = sum(scores.values()) or 1.0
    confidence = best_score / total

    # If confidence is below threshold, ask user to disambiguate
    if confidence < DISAMBIGUATE_THRESHOLD or (
        abs(scores["visual_search"] - scores["cv_triage"]) < 0.10
        and not signals.get("query_visual_search")
        and not signals.get("query_cv_triage")
    ):
        return {
            "intent": "disambiguate",
            "confidence": confidence,
            "reason": "Ambiguous intent — asking user to clarify",
            "signals": signals,
            "scores": scores,
        }

    reasons = {
        "visual_search": "Routing to visual product search",
        "cv_triage": "Routing to return/complaint triage",
        "faq": "Routing to FAQ/help",
    }

    return {
        "intent": best_intent,
        "confidence": round(confidence, 3),
        "reason": reasons.get(best_intent, "Classified by signal matrix"),
        "signals": signals,
        "scores": scores,
    }
