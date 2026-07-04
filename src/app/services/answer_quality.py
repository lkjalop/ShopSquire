from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple


_BUDGET_HINT = re.compile(r"\$?\s*([\d,]{3,6})")
_RANGE_HINT = re.compile(r"\$?\s*([\d,]{2,6})\s*(?:-|to|and)\s*\$?\s*([\d,]{2,6})", re.I)


def _to_int(v: str | None) -> int | None:
    if not v:
        return None
    try:
        return int(str(v).replace(",", "").strip())
    except Exception:
        return None


def _extract_price_range_from_message(message: str) -> Tuple[int | None, int | None]:
    m = _RANGE_HINT.search(str(message or ""))
    if not m:
        return (None, None)
    lo = _to_int(m.group(1))
    hi = _to_int(m.group(2))
    if lo is None or hi is None:
        return (None, None)
    return (min(lo, hi), max(lo, hi))


def _extract_budget_threshold(query: str) -> int | None:
    q = str(query or "").lower()
    m = re.search(r"(?:over|above|more than|greater than)\s*\$?\s*([\d,]{3,6})", q)
    if m:
        return _to_int(m.group(1))
    return None


def _extract_query_budget_bounds(query: str) -> Tuple[int | None, int | None]:
    q = str(query or "").lower()
    # A cue-anchored OR $-anchored range so bare bulk phrasings parse too: "budget 1500 to 1900",
    # "price 1500-1900", "$1500-$1900 each". Without an anchor a bare "1500 to 1900" is too ambiguous
    # (spec ranges, counts) — the anchor (between/from/budget/price/a leading $) keeps it a BUDGET range.
    for pat in (
        r"(?:between|from|budget(?:\s+(?:is|of))?|price(?:\s+range)?)\s*\$?\s*([\d,]{3,6})\s*(?:and|to|-|–|—)\s*\$?\s*([\d,]{3,6})",
        r"\$\s*([\d,]{3,6})\s*(?:and|to|-|–|—)\s*\$?\s*([\d,]{3,6})",
    ):
        m_range = re.search(pat, q)
        if m_range:
            lo = _to_int(m_range.group(1))
            hi = _to_int(m_range.group(2))
            if lo is not None and hi is not None:
                return (min(lo, hi), max(lo, hi))
    m_under = re.search(r"(?:under|below|less than|<)\s*\$?\s*([\d,]{2,6})", q)
    if m_under:
        return (None, _to_int(m_under.group(1)))
    m_over = re.search(r"(?:over|above|more than|>)\s*\$?\s*([\d,]{2,6})", q)
    if m_over:
        return (_to_int(m_over.group(1)), None)
    return (None, None)


_DAMAGE_RE = re.compile(
    r"\b(broken|damaged|cracked|shattered|not working|faulty|dead pixel|screen damage|bsod|"
    r"blue screen|stop code|repair|replacement)\b")
_POLICY_WORD_RE = re.compile(r"\b(warranty|returns?|refunds?|support)\b")
_POST_PURCHASE_RE = re.compile(
    r"\b(my|i bought|i purchased|i got|i received|i ordered|arrived|came with|send (it )?back)\b")


def is_support_claim(query: str) -> bool:
    """CLAIM-CHECKED support detection, shared by every lane that routes to repair/return handling.

    The support lane may only claim a turn that is genuinely a post-purchase CLAIM: damage/fault words are
    inherently post-purchase; bare policy words (warranty/return/refund/support) additionally need
    possession/purchase context. Without this, "what is your warranty policy?" (pre-sales FAQ) and
    "gaming laptop under 2000. also what warranty do you offer?" (mixed ask) were hijacked into
    photo-triage with zero products — the same disease as the inventory-lane "can i get" hijack."""
    q = str(query or "").strip().lower()
    if not q:
        return False
    if _DAMAGE_RE.search(q):
        return True
    return bool(_POLICY_WORD_RE.search(q) and _POST_PURCHASE_RE.search(q))


_POLICY_TOPIC_RES = {
    "warranty": re.compile(r"\bwarrant\w*\b"),
    "returns": re.compile(r"\breturns?\b|\brefunds?\b|\bchange of mind\b"),
    "shipping": re.compile(r"\bshipping\b|\bdelivery\b|\bship\b|\bfreight\b"),
    "price_match": re.compile(r"\bprice\s*match\w*\b|\bbeat\s+(?:the\s+)?price\b"),
}


def policy_faq_answer(query: str) -> Optional[str]:
    """Answer a PRE-SALES policy question from the StoreProfile's ``policy_faq`` slot — content is DATA
    the store wrote, never invented by core (prohibited-claims discipline). Returns the matched topics'
    text, or an honest "a teammate will confirm" line when the store hasn't filled the slot, or None when
    the query isn't a policy question at all (caller proceeds normally). Post-purchase claims are NOT
    handled here — is_support_claim() owns those."""
    q = str(query or "").strip().lower()
    if not q or is_support_claim(q):
        return None
    topics = [t for t, rx in _POLICY_TOPIC_RES.items() if rx.search(q)]
    # only claim clearly policy-shaped asks: a topic word + a question/policy cue
    if not topics or not re.search(r"\bpolic\w+\b|\bwhat(?:'s| is| are)\b|\bhow\b|\bdo you\b|\bwhat do you\b|\?", q):
        return None
    try:
        from src.app.platform.store_profile import profile_slot
        slot = profile_slot("policy_faq", default=None)
    except Exception:
        slot = None
    if not isinstance(slot, dict) or not slot:
        return ("Good pre-purchase question — I don't want to guess policy terms, so I've flagged it for a "
                "teammate to confirm the specifics. Meanwhile I can keep helping with products.")
    parts = [str(slot[t]) for t in topics if slot.get(t)]
    if not parts:
        return ("That policy detail isn't in my approved answers yet — a teammate will confirm it. "
                "Meanwhile I can keep helping with products.")
    return " ".join(parts)


def decompose_intent_and_questions(
    *,
    query: str,
    turn_intent: str | None,
    image_cv_signals: Dict[str, Any] | None,
    has_image: bool,
) -> Dict[str, Any]:
    q = str(query or "").lower()
    ti = str(turn_intent or "SEARCH").upper()
    primary_intent = "buy"
    if ti == "COMPARE":
        primary_intent = "compare"
    elif ti == "SUPPORT_CLAIM":
        primary_intent = "support"
    elif "escalat" in q:
        primary_intent = "escalate"

    required_answers: List[str] = []
    if any(tok in q for tok in ("budget", "under", "over", "between", "$")):
        required_answers.append("budget_recommendation")
    if any(tok in q for tok in ("do you have", "available", "in stock", "which", "options")):
        required_answers.append("product_availability")
    if any(tok in q for tok in ("how soon", "when", "how long", "urgent", "asap")):
        required_answers.append("eta_to_resolve")
    if "product_availability" in required_answers or "eta_to_resolve" in required_answers:
        required_answers.append("fallback_options")

    sig = image_cv_signals if isinstance(image_cv_signals, dict) else {}
    multimodal_signals = {
        "has_image": bool(has_image),
        "qr_code_detected": bool(sig.get("qr_code_detected")),
        "qr_prompt_injection": bool(sig.get("qr_prompt_injection")),
        "qr_external_url_detected": bool(sig.get("qr_external_url_detected")),
        "damage_detected": bool(sig.get("damage_detected")),
        "image_confidence": float(sig.get("confidence") or 0.0),
    }
    return {
        "primary_intent": primary_intent,
        "required_answers": required_answers,
        "multimodal_signals": multimodal_signals,
    }


def select_template(
    *,
    decomp: Dict[str, Any],
    query: str,
    products: List[Dict[str, Any]],
    image_cv_signals: Dict[str, Any] | None,
) -> Dict[str, str]:
    sig = image_cv_signals if isinstance(image_cv_signals, dict) else {}
    if bool(sig.get("qr_prompt_injection") or sig.get("qr_external_url_detected")):
        return {"template_id": "cv_reupload_with_text_fallback_template", "reason": "cv_hard_block"}
    if str(decomp.get("primary_intent") or "") == "support":
        return {"template_id": "repair_return_eta_template", "reason": "support_routing"}
    if not products:
        return {"template_id": "no_match_explain_template", "reason": "no_products"}
    if "budget_recommendation" in (decomp.get("required_answers") or []):
        return {"template_id": "budget_decision_template", "reason": "budget_query"}
    return {"template_id": "default_template", "reason": "general"}


def score_answer_coverage(*, query: str, message: str, required_answers: List[str]) -> Dict[str, Any]:
    msg = str(message or "")
    first_sentence = re.split(r"[.!?]\s+", msg.strip(), maxsplit=1)[0].strip().lower()
    covered: List[str] = []
    missing: List[str] = []
    direct_ok = bool(first_sentence) and any(
        first_sentence.startswith(x)
        for x in ("yes", "no", "usually", "currently", "none", "you should", "for your case")
    )
    if direct_ok:
        covered.append("direct_answer_first_sentence")
    else:
        missing.append("direct_answer_first_sentence")

    for need in (required_answers or []):
        if need == "budget_recommendation":
            if _RANGE_HINT.search(msg) or re.search(r"\$\s*[\d,]{3,6}", msg):
                covered.append(need)
            else:
                missing.append(need)
        elif need == "eta_to_resolve":
            if re.search(r"\b(min|mins|minute|minutes|hour|hours|day|days|session)\b", msg, re.I):
                covered.append(need)
            else:
                missing.append(need)
        elif need == "product_availability":
            if any(tok in msg.lower() for tok in ("in stock", "not currently", "none", "available", "closest")):
                covered.append(need)
            else:
                missing.append(need)
        elif need == "fallback_options":
            if any(tok in msg.lower() for tok in ("alternative", "closest", "can widen", "open to", "alert")):
                covered.append(need)
            else:
                missing.append(need)
    return {"covered": covered, "missing": missing, "ok": len(missing) == 0}


def _render_budget_decision(*, query: str, products: List[Dict[str, Any]], base_message: str) -> str:
    # Prefer stated user budget over any price range found in the LLM message text
    q_lo, q_hi = _extract_query_budget_bounds(query)
    # Also try "around $N" / "budget $N" / "about $N" patterns
    _around = re.search(r"(?:around|about|roughly|approx\.?|budget\s+(?:of\s+)?)\$?\s*([\d,]{3,6})", str(query or ""), re.I)
    if _around and q_hi is None:
        _v = _to_int(_around.group(1))
        if _v:
            q_hi = _v
    lo_msg, hi_msg = _extract_price_range_from_message(base_message)
    prices = [int(float(p.get("price") or 0)) for p in (products or []) if p.get("price") is not None]
    if prices and (lo_msg is None or hi_msg is None):
        lo_msg, hi_msg = min(prices), max(prices)
    # The band must reflect the BUYER'S budget, not the raw product price range — over-budget
    # "performance-fit" lane items must never inflate it (the $1,900 query that read "$1,199-$5,999").
    # Floor = cheapest IN-BUDGET option; ceiling = the buyer's stated cap when they gave one.
    if prices:
        in_budget = [p for p in prices if (q_hi is None or p <= q_hi)]
        lo_msg = min(in_budget) if in_budget else min(prices)
        hi_msg = q_hi if q_hi is not None else max(prices)
    threshold = _extract_budget_threshold(query)
    direct = None
    if threshold is not None and hi_msg is not None:
        direct = "Usually no." if hi_msg <= threshold else "It depends."
    if direct is None:
        direct = "For your case,"
    if lo_msg is not None and hi_msg is not None:
        # Never print a reversed band (a mis-parsed cap once produced "$1,599-$1,500"): the floor is the
        # cheapest in-budget option and the ceiling the buyer's cap, so order them defensively.
        lo_band, hi_band = min(lo_msg, hi_msg), max(lo_msg, hi_msg)
        return f"{direct} a practical budget band is ${lo_band:,}-${hi_band:,}. {base_message}".strip()
    return f"{direct} {base_message}".strip()


def _render_no_match(*, query: str, products: List[Dict[str, Any]]) -> str:
    lo, hi = _extract_query_budget_bounds(query)
    if hi is not None and lo is None:
        return (
            f"No, not currently in-catalog under ${hi:,}. "
            "Closest alternatives are above that range. I can show best-value non-Apple options or set an Apple-only stock alert."
        )
    if lo is not None and hi is not None:
        return (
            f"None currently in-catalog between ${lo:,} and ${hi:,}. "
            "Closest alternatives are outside this band. I can widen budget or show nearest in-stock options."
        )
    return "No exact in-catalog match right now. I can show closest in-stock alternatives or widen constraints."


def _render_cv_fallback(*, query: str, base_message: str) -> str:
    return (
        "I can't trust this image yet because of QR/overlay risk. "
        "Please reupload a clean product-only photo (1-2 min triage). "
        f"Meanwhile, for your question: {base_message}"
    )


def _render_support_eta(*, query: str, base_message: str) -> str:
    return (
        "Fastest path: submit a clean photo now (1-2 min triage), then I can route to repair/return guidance. "
        "If urgent, I can open human support in this session. "
        f"{base_message}"
    )


def _dedupe_warning_blocks(message: str) -> str:
    msg = str(message or "")
    parts = [p.strip() for p in re.split(r"\n{2,}", msg) if p.strip()]
    seen = set()
    out: List[str] = []
    for p in parts:
        key = p.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    return "\n\n".join(out).strip() or msg


def apply_answer_quality(
    *,
    query: str,
    assistant_message: str | None,
    turn_intent: str | None,
    products: List[Dict[str, Any]],
    image_cv_signals: Dict[str, Any] | None,
    has_image: bool,
    buyer_persona: str | None,
    brand_name: str | None,
) -> Dict[str, Any]:
    msg = str(assistant_message or "").strip()
    decomp = decompose_intent_and_questions(
        query=query,
        turn_intent=turn_intent,
        image_cv_signals=image_cv_signals,
        has_image=has_image,
    )
    templ = select_template(
        decomp=decomp,
        query=query,
        products=products,
        image_cv_signals=image_cv_signals,
    )
    template_id = templ.get("template_id") or "default_template"

    rewritten = msg
    if template_id == "budget_decision_template":
        rewritten = _render_budget_decision(query=query, products=products, base_message=msg)
    elif template_id == "no_match_explain_template":
        rewritten = _render_no_match(query=query, products=products)
    elif template_id == "cv_reupload_with_text_fallback_template":
        rewritten = _render_cv_fallback(query=query, base_message=msg or "I can continue with text-only recommendations.")
    elif template_id == "repair_return_eta_template":
        rewritten = _render_support_eta(query=query, base_message=msg or "I will prepare return/repair next steps.")

    cov = score_answer_coverage(
        query=query,
        message=rewritten,
        required_answers=decomp.get("required_answers") or [],
    )
    if not bool(cov.get("ok")) and "direct_answer_first_sentence" in (cov.get("missing") or []):
        if template_id == "budget_decision_template":
            rewritten = _render_budget_decision(query=query, products=products, base_message=rewritten)
        elif template_id == "no_match_explain_template":
            rewritten = _render_no_match(query=query, products=products)

    persona = str(buyer_persona or "").strip().lower()
    if persona in {"student", "budget_student"} and "budget_recommendation" in (decomp.get("required_answers") or []):
        rewritten = f"{rewritten} Student baseline: aim for value-first specs before premium upgrades."
    bname = str(brand_name or "").strip()
    if bname:
        rewritten = f"{bname}: {rewritten}"

    rewritten = _dedupe_warning_blocks(rewritten)
    cov2 = score_answer_coverage(
        query=query,
        message=rewritten,
        required_answers=decomp.get("required_answers") or [],
    )
    return {
        "assistant_message": rewritten,
        "intent_decomposed": decomp,
        "template_selected": {"template_id": template_id, "reason": templ.get("reason")},
        "answer_coverage_scored": cov2,
    }


