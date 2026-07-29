"""Canonical query classification service (Sprint R1 extraction).

All query intent classification belongs here. The recommend router should
import from this module rather than using inline private functions.

Covers:
- Follow-up explain detection
- Turn intent classification (SEARCH / FILTER / COMPARE / EXPLAIN / SUPPORT_CLAIM)
- Off-domain / unsupported intent detection
- Requirements query detection
- Stock query detection (delegates to inventory_query_service)
- Budget question detection
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional


# ── Follow-up explain query ───────────────────────────────────────────────────

_FOLLOWUP_EXPLAIN_RE = re.compile(
    r"\b(why|detailed|detail|explain|those|these|them|that one|this one|"
    r"list them|list all|all \d+|those \d+|compare them|why this|why those|"
    r"why are they|why did you|how did you|what made you|tell me more|"
    r"what does|how does|can you elaborate|walk me through|"
    r"why pick|why picked|why chose|why chosen|why recommend|"
    r"how is it|how are they|how are these|what.s the difference|"
    r"break it down|rank them|score them|rate them|pros and cons|"
    r"more about|what about|show me more|more info|more detail|"
    r"more options|anything else|tell me about|what makes|"
    r"give me more|i want more|show more|sounds good|"
    r"go on|continue|keep going|what else|"
    r"not sure|i'm confused|confused|don't understand|"
    r"what do you mean|what does that mean|huh|"
    r"can you explain|please explain|explain more)\b",
    re.IGNORECASE,
)


def is_followup_explain_query(query: Optional[str]) -> bool:
    """Return True when the query is a follow-up asking for explanation of prior results."""
    q = str(query or "").strip()
    if not q:
        return False
    return bool(_FOLLOWUP_EXPLAIN_RE.search(q))


def is_standalone_search(query: Optional[str]) -> bool:
    """Return whether a turn contains its own product/budget search subject."""
    value = str(query or "").strip().lower()
    if not value:
        return False
    from src.app.services.recommend_budget_parsing import (
        extract_explicit_budget_override,
    )

    if extract_explicit_budget_override(value):
        return True
    category_words = (
        "laptop",
        "notebook",
        "ultrabook",
        "macbook",
        "chromebook",
        "desktop",
        "tower",
        "workstation",
        "tablet",
        "ipad",
        "phone",
        "smartphone",
        "monitor",
        "pc",
        "computer",
        "headset",
        "keyboard",
        "mouse",
    )
    if any(re.search(rf"\b{re.escape(word)}\b", value) for word in category_words):
        return True
    try:
        from src.app.services.query_decomposer import decompose

        plan = decompose(value)
        if getattr(plan, "answer_without_products", False):
            return False
        if (
            getattr(plan, "category", None)
            or str(getattr(plan, "intent", "")) == "recommendation_multi"
        ):
            return True
        return any(
            getattr(question, "use_cases", None)
            or getattr(question, "hard_constraints", None)
            for question in getattr(plan, "sub_questions", []) or []
        )
    except Exception:
        return False


# ── Off-domain / unsupported intent ──────────────────────────────────────────

_FRESH_SEARCH_REQUEST_RE = re.compile(
    r"\b(i|we)\s+(?:need|want|am looking for|are looking for|"
    r"am thinking (?:to|of) (?:buying|getting)|are thinking (?:to|of) "
    r"(?:buying|getting))\b|"
    r"\b(?:recommend|find|show)\s+(?:me|us)\b",
    re.IGNORECASE,
)


def is_fresh_search_request(query: Optional[str]) -> bool:
    """Return whether a rationale-bearing turn supplies its own search subject."""
    value = str(query or "").strip()
    return bool(_FRESH_SEARCH_REQUEST_RE.search(value) and is_standalone_search(value))


_OFF_DOMAIN_RE = re.compile(
    r"\b(can i get your number|what(?:'s| is) your number|give me your number|"
    r"date me|go out with me|sexy|hot|"
    r"big\s*mac|burger|fries|mcdonalds|"
    r"write.*code|write.*essay|write.*email|compose.*poem|"
    r"translate|what is the weather|stock.*price|stock.*market|"
    r"weather|forecast|is\s+it\s+raining|going\s+to\s+rain|will\s+it\s+rain|"
    r"recipe|cook|bake|pasta|pizza|lasagne|sandwich|"
    r"who\s+won|the\s+score|match\s+last\s+night|football|cricket|"
    r"nba|nfl|world\s+cup|tell\s+me\s+a\s+joke|knock\s+knock|sing\s+me|"
    r"write\s+me\s+a\s+poem|"
    r"capital\s+of|who\s+is\s+the\s+president|meaning\s+of\s+life|"
    r"what\s+year\s+did|medical.*advice|legal.*advice|"
    r"diagnose|diagnosis|prescription|drug|medication|"
    r"political|election|vote|president|prime.minister)\b",
    re.IGNORECASE,
)

_OFF_DOMAIN_CALCULATION_RE = re.compile(
    r"^\s*(?:(?:what|whats|what's)\s+is|calculate)\s+\d+\s*"
    r"(?:[-+*x/]|times|plus|minus|divided\s+by)\s*\d+",
    re.IGNORECASE,
)

_UNSUPPORTED_INTENT_RE = re.compile(
    r"\b(ignore.*instructions?|system.*prompt|developer.*mode|"
    r"jailbreak|bypass.*filter|override.*policy|"
    r"pretend.*you.*are|roleplay.*as|act.*as.*if)\b",
    re.IGNORECASE,
)

_GREETING_RE = re.compile(
    r"^\s*(?:hi+|hey+|hello+|helo|yo|sup|hiya|howdy|greetings|"
    r"good\s+(?:morning|afternoon|evening)|help|menu|start|get\s+started|"
    r"what\s+can\s+you\s+do|what\s+do\s+you\s+do|who\s+are\s+you|"
    r"what\s+are\s+you|what\s+is\s+this|how\s+(?:do|does)\s+(?:you|this|it)\s+work|"
    r"what\s+can\s+i\s+(?:do|ask)|can\s+you\s+help(?:\s+me)?)"
    r"(?:\s+there|\s+friend)?\s*[?!.]*\s*$",
    re.IGNORECASE,
)


def is_off_domain_query(query: Optional[str]) -> bool:
    """Return True when the query is clearly off-domain (not a shopping/support task)."""
    text = str(query or "")
    return bool(_OFF_DOMAIN_RE.search(text) or _OFF_DOMAIN_CALCULATION_RE.search(text))


def is_greeting_query(query: Optional[str]) -> bool:
    """Return True only for a standalone greeting/capabilities request."""
    return bool(_GREETING_RE.match(str(query or "").strip()))


def has_unsupported_intent(query: Optional[str]) -> bool:
    """Return True when the query contains prompt injection / jailbreak patterns."""
    return bool(_UNSUPPORTED_INTENT_RE.search(str(query or "")))


# ── Requirements query ────────────────────────────────────────────────────────

_REQUIREMENTS_RE = re.compile(
    r"\b(need.*for|requirements?.*for|specs?.*for|what.*need.*to|"
    r"what.*required|minimum.*specs?|recommend.*for|best.*for|"
    r"suited.*for|suitable.*for|designed.*for|built.*for)\b",
    re.IGNORECASE,
)


def is_requirements_query(query: Optional[str]) -> bool:
    """Return True when the user is asking about requirements for a use-case."""
    return bool(_REQUIREMENTS_RE.search(str(query or "")))


# ── Budget question ───────────────────────────────────────────────────────────

_BUDGET_QUESTION_RE = re.compile(
    r"\b(is\s+\$|is\s+that\s+enough|is\s+my\s+budget|enough\s+for|"
    r"can\s+i\s+(afford|get)|will\s+\$|how\s+much\s+does|"
    r"is\s+\$?\d+\s+(?:(?:dollars?|usd|aud|gbp|eur|k)\s+)?(?:enough|ok|okay|sufficient)|"
    r"(good|decent|ok)\s+budget)\b",
    re.IGNORECASE,
)


def is_budget_question(query: Optional[str]) -> bool:
    """Return True when user is asking a yes/no budget sufficiency question."""
    return bool(_BUDGET_QUESTION_RE.search(str(query or "")))


# ── Turn intent classification ────────────────────────────────────────────────

def classify_turn_intent(
    *,
    query: Optional[str],
    nlp: Optional[Dict[str, Any]],
    followup_explain: bool,
    explicit_constraint_update: bool,
) -> str:
    """Classify the user's turn intent.

    Returns one of: EXPLAIN | SUPPORT_CLAIM | COMPARE | FILTER | SEARCH
    """
    q = str(query or "").strip().lower()
    if followup_explain:
        return "EXPLAIN"
    if re.search(
        r"\b(warranty|return|refund|broken|damaged|cracked|shattered|repair|"
        r"replacement|support|not working|faulty|dead pixel|screen damage|"
        r"bsod|blue screen|stop code|where is my order|order status|"
        r"track(?:ing)? (?:my |the )?(?:order|shipment|delivery)|"
        r"has not arrived|hasn't arrived|not arrived|not received|"
        r"late delivery|missing (?:order|shipment|delivery))\b",
        q,
    ):
        return "SUPPORT_CLAIM"
    if re.search(r"\b(compare|vs|versus|difference|which one|better)\b", q):
        return "COMPARE"
    n_intent = str(((nlp or {}).get("intent") or "")).strip().lower()
    if n_intent == "compare":
        return "COMPARE"
    if explicit_constraint_update or re.search(
        r"\b(under|below|between|over|above|budget|brand|ram|ssd|gpu|cpu|16gb|32gb)\b", q
    ):
        return "FILTER"
    return "SEARCH"


# ── Coarse product category ───────────────────────────────────────────────────

_CATEGORY_PATTERNS: List[tuple] = [
    ("laptop", re.compile(r"\b(laptops?|notebooks?|ultrabooks?|macbooks?|chromebooks?|thinkpads?|spectres?|legions?|rog)\b", re.I)),
    ("desktop", re.compile(r"\b(desktop|tower|mini.pc|nuc|all.in.one)\b", re.I)),
    ("monitor", re.compile(r"\b(monitor|display|screen|4k|1440p|curved)\b", re.I)),
    ("keyboard", re.compile(r"\b(keyboard|mechanical|keycap|switch)\b", re.I)),
    ("mouse", re.compile(r"\b(mouse|mice|trackpad|trackball)\b", re.I)),
    ("headset", re.compile(r"\b(headset|headphone|earphone|earbuds|airpods)\b", re.I)),
    ("phone", re.compile(r"\b(phone|smartphone|iphone|android|samsung)\b", re.I)),
    ("tablet", re.compile(r"\b(tablet|ipad|surface|android.*tablet)\b", re.I)),
    ("storage", re.compile(r"\b(ssd|hdd|hard.*drive|external.*drive|nvme|nas)\b", re.I)),
    ("gpu", re.compile(r"\b(gpu|graphics.*card|rtx|radeon|geforce)\b", re.I)),
    ("cpu", re.compile(r"\b(cpu|processor|ryzen|intel.*core|amd)\b", re.I)),
]


def coarse_product_category(query: Optional[str]) -> Optional[str]:
    """Return the most likely product category from the query, or None."""
    q = str(query or "")
    for category, pattern in _CATEGORY_PATTERNS:
        if pattern.search(q):
            return category
    return None


# ── Classifier summary (used by NQE and scoring) ──────────────────────────────

def classify_query(
    query: Optional[str],
    *,
    nlp: Optional[Dict[str, Any]] = None,
    kv: Optional[Dict[str, Any]] = None,
    has_image: bool = False,
) -> Dict[str, Any]:
    """Run all classifiers and return a summary dict.

    This is the single entry point for all query classification. Callers should
    use this rather than calling individual classifier functions.
    """
    followup_explain = is_followup_explain_query(query)
    budget_question = is_budget_question(query)
    off_domain = is_off_domain_query(query)
    injection = has_unsupported_intent(query)
    requirements = is_requirements_query(query)

    from src.app.services.inventory_query_service import is_inventory_query as _inv_q
    inventory_intent = _inv_q(query)

    explicit_constraint = bool(
        kv and any(kv.get(k) for k in ("budget_min", "budget_max", "brands", "specs"))
    )
    turn_intent = classify_turn_intent(
        query=query,
        nlp=nlp,
        followup_explain=followup_explain and not is_fresh_search_request(query),
        explicit_constraint_update=explicit_constraint,
    )
    category = coarse_product_category(query)

    return {
        "followup_explain": followup_explain,
        "budget_question": budget_question,
        "off_domain": off_domain,
        "injection_attempt": injection,
        "requirements_query": requirements,
        "inventory_intent": inventory_intent,
        "turn_intent": turn_intent,
        "category": category,
        "has_image": has_image,
    }
