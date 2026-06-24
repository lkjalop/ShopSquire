from __future__ import annotations

"""Query decomposition & intent routing (roadmap WS2.1 / WS2.3 / WS2.4).

Turns a raw shopper query into a structured ``QueryPlan`` so the recommend
pipeline can:

  * route comparison/knowledge questions to a *conceptual* answer path instead
    of returning a blank product list (WS2.2);
  * honour EVERY intent in a multi-intent query ("gaming + video editing +
    portable") rather than letting one persona win (WS2.3);
  * convert natural-language constraints ("240fps", "portable", "32GB") into
    HARD filters the retriever can enforce (WS2.4 → WS3.2).

Pure functions, no LLM, no I/O — fast and unit-testable. Builds on
``query_classifier`` for category / budget-question detection.
"""

import re
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Dict, List, Optional

from src.app.services.query_classifier import (
    coarse_product_category,
    is_budget_question,
    is_followup_explain_query,
)

# ── Intent constants ──────────────────────────────────────────────────────────
INTENT_PRODUCT_SEARCH = "product_search"
INTENT_COMPARISON = "comparison"
INTENT_KNOWLEDGE = "knowledge"
INTENT_MULTI = "recommendation_multi"
INTENT_SUPPORT = "support"
INTENT_AVAILABILITY = "availability"  # fulfilment/lead-time ("can you deliver in 4 weeks?")

# ── Number words (agnostic) — so "ten laptops" / "in fourteen days" parse like their digit forms ──
_NUMBER_WORDS: Dict[str, int] = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
    "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20,
    "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
    "hundred": 100, "dozen": 12,
}
# longest-first so "fourteen" wins over "four" in the alternation
_NUMBER_WORD_ALT = "|".join(sorted((re.escape(k) for k in _NUMBER_WORDS), key=len, reverse=True))


def _token_to_int(tok: str) -> Optional[int]:
    """Digit string or number word → int (None if neither). Agnostic."""
    t = str(tok or "").strip().lower()
    if t.isdigit():
        return int(t)
    return _NUMBER_WORDS.get(t)

# Availability / fulfilment / lead-time questions (agnostic — no vertical literals).
_AVAILABILITY_RE = re.compile(
    r"\b("
    r"in\s+\d+\s+(?:day|week|month)s?"
    r"|can\s+(?:you|we|i)\s+(?:get|deliver|ship|fulfil|fulfill|source|receive)"
    r"|when\s+(?:can|will|would|do)\s+(?:you|we|i|it|they)"
    r"|how\s+(?:soon|long)"
    r"|lead[\s-]?time|in\s+stock\s+by|available\s+(?:by|in|within)"
    r"|deliver(?:y|ed|able)?\b|restock|back\s*order|would\s+there\s+be\s+any"
    r")\b",
    re.IGNORECASE,
)


def _extract_availability_horizon(q: str) -> Optional[int]:
    """Days from an availability horizon ('in 4 weeks' / 'in fourteen days' → 28 / 14). Agnostic."""
    m = re.search(
        rf"\b(?:in|within|by)\s+(\d{{1,3}}|{_NUMBER_WORD_ALT})\s+(day|week|month)s?\b",
        str(q or "").lower(),
    )
    if not m:
        return None
    n = _token_to_int(m.group(1))
    if n is None:
        return None
    return n * {"day": 1, "week": 7, "month": 30}[m.group(2)]

_SUPPORT_RE = re.compile(
    r"\b(warranty|return|refund|broken|damaged|cracked|shattered|repair|"
    r"replacement|faulty|not working|dead pixel|bsod|blue screen|stop code)\b",
    re.IGNORECASE,
)

# Comparison: two named things being weighed against each other.
_COMPARISON_RE = re.compile(
    r"\b(vs\.?|versus|compare|comparison|difference between|which is better|"
    r"which one is better|better than|pros and cons of)\b",
    re.IGNORECASE,
)

# Knowledge: conceptual question answerable WITHOUT a product list.
_KNOWLEDGE_RE = re.compile(
    r"(what'?s the difference|what is the difference|"
    r"\bdo i (really )?need\b|\bhow much (ram|vram|storage|memory)\b|"
    r"\bis (an? )?\w+ (enough|better|worth)\b|\bwhat does .+ mean\b|"
    r"\bwhich (gpu|cpu|processor|ram|ssd|screen|panel) (is|should)\b|"
    r"\bwhat'?s? (better|the best) .* (for|between)\b)",
    re.IGNORECASE,
)

# Explanation/rationale follow-up about a PRIOR shortlist ("why those?", "why these ones?",
# "why did you pick that?") — a conceptual answer about existing results, NOT a fresh product search.
_EXPLAIN_REF_RE = re.compile(
    r"\bwhy\s+(?:did\s+you\s+)?(?:(?:pick|choose|chose|recommend|suggest\w*|get|go\s+with)\s+)?"
    r"(those|these|them|that|this|it|the\s+(?:first|second|third|top|one|ones))\b",
    re.IGNORECASE,
)

# Listy phrasing that forces product_search even if "what/which" appears.
_PRODUCT_LISTY_RE = re.compile(
    r"\b(show me|find me|recommend|suggest|looking for|i want|i need a|"
    r"best .* (laptop|pc|desktop|phone|tablet|monitor|headset)|"
    r"good .* (laptop|pc|desktop|gaming|for gaming))\b",
    re.IGNORECASE,
)

# ── Use cases (multi-intent detection) ────────────────────────────────────────
# FLAVOUR excised to the StoreProfile (R2). The inline dicts below are the proven
# fallback (parity-tested in test_query_decomposer_profile.py); the active patterns are
# loaded from config/store_profiles/<vertical>.json so a pharmacy store decomposes with
# pharmacy use-cases, not laptop gaming/GPU assumptions.
_USE_CASE_PATTERNS_FALLBACK: Dict[str, "re.Pattern"] = {
    "gaming": re.compile(r"\b(gaming|gamer|esports|fps|valorant|fortnite|cyberpunk|aaa|triple ?a|ray ?tracing)\b", re.I),
    "video_editing": re.compile(r"\b(video edit\w*|premiere|davinci|resolve|4k edit\w*|content creat\w*|youtub\w*|streaming|render\w*)\b", re.I),
    "programming": re.compile(r"\b(coding|programming|developer|software dev|docker|compile|android studio|xcode|ide)\b", re.I),
    "ml_ai": re.compile(r"\b(machine learning|deep learning|ai training|train\w* (a )?model|llm|cuda|tensor|pytorch|data science)\b", re.I),
    "cad_3d": re.compile(r"\b(cad|autocad|solidworks|revit|3d model\w*|blender|rendering|engineering student)\b", re.I),
    "photo": re.compile(r"\b(photo edit\w*|photoshop|lightroom|raw photo)\b", re.I),
    "office": re.compile(r"\b(office work|excel|spreadsheet|word processing|email|business use|productivity)\b", re.I),
    "study": re.compile(r"\b(student|university|uni|college|study|school work|note ?taking)\b", re.I),
}
_DGPU_USE_CASES_FALLBACK = {"gaming", "video_editing", "ml_ai", "cad_3d"}
_PORTABLE_RE_FALLBACK = re.compile(r"\b(portable|lightweight|light ?weight|thin and light|ultrabook|ultra ?portable|travel|carry around|commut\w*)\b", re.I)


def _load_use_case_patterns() -> Dict[str, "re.Pattern"]:
    try:
        from src.app.platform.store_profile import profile_slot
        raw = profile_slot("use_case_patterns", default=None)
        if isinstance(raw, dict) and raw:
            return {uc: re.compile(p, re.I) for uc, p in raw.items()}
    except Exception:
        pass
    return _USE_CASE_PATTERNS_FALLBACK


def _load_dgpu_use_cases() -> set:
    try:
        from src.app.platform.store_profile import profile_slot
        ucs = profile_slot("use_cases", default={}) or {}
        s = {uc for uc, meta in ucs.items() if isinstance(meta, dict) and meta.get("needs_dedicated_gpu")}
        if s:
            return s
    except Exception:
        pass
    return _DGPU_USE_CASES_FALLBACK


def _load_portable_re() -> "re.Pattern":
    try:
        from src.app.platform.store_profile import profile_slot
        p = profile_slot("portable_pattern", default=None)
        if p:
            return re.compile(p, re.I)
    except Exception:
        pass
    return _PORTABLE_RE_FALLBACK


_USE_CASE_PATTERNS: Dict[str, "re.Pattern"] = _load_use_case_patterns()
_DGPU_USE_CASES = _load_dgpu_use_cases()
_PORTABLE_RE = _load_portable_re()


# ── Per-request (active-vertical) resolution ─────────────────────────────────────────────────────
# The constants above are computed at IMPORT (electronics default) and kept only for back-compat.
# The decision path below resolves the ACTIVE vertical's patterns PER REQUEST, cached by profile id
# (cache-by-resolved-id, like store_profile) — so the request-boundary selector actually reaches the
# decomposer and a pharmacy/fashion request is NOT scored against electronics use-cases.
@lru_cache(maxsize=8)
def _use_case_patterns_for(profile_id: str) -> Dict[str, "re.Pattern"]:
    try:
        from src.app.platform.store_profile import profile_slot
        raw = profile_slot("use_case_patterns", profile_id=profile_id, default=None)
        if isinstance(raw, dict) and raw:
            return {uc: re.compile(p, re.I) for uc, p in raw.items()}
    except Exception:
        pass
    return _USE_CASE_PATTERNS_FALLBACK


@lru_cache(maxsize=8)
def _dgpu_use_cases_for(profile_id: str) -> set:
    try:
        from src.app.platform.store_profile import profile_slot
        ucs = profile_slot("use_cases", profile_id=profile_id, default={}) or {}
        s = {uc for uc, meta in ucs.items() if isinstance(meta, dict) and meta.get("needs_dedicated_gpu")}
        # An empty set is a VALID answer for a non-electronics vertical (no dGPU concept) — only fall
        # back to the electronics set when the profile has no use_cases at all.
        if ucs:
            return s
    except Exception:
        pass
    return _DGPU_USE_CASES_FALLBACK


@lru_cache(maxsize=8)
def _portable_re_for(profile_id: str) -> "re.Pattern":
    try:
        from src.app.platform.store_profile import profile_slot
        p = profile_slot("portable_pattern", profile_id=profile_id, default=None)
        if p:
            return re.compile(p, re.I)
    except Exception:
        pass
    return _PORTABLE_RE_FALLBACK


def _active_use_case_patterns() -> Dict[str, "re.Pattern"]:
    from src.app.platform.store_profile import active_profile_id
    return _use_case_patterns_for(active_profile_id())


def _active_dgpu_use_cases() -> set:
    from src.app.platform.store_profile import active_profile_id
    return _dgpu_use_cases_for(active_profile_id())


def _active_portable_re() -> "re.Pattern":
    from src.app.platform.store_profile import active_profile_id
    return _portable_re_for(active_profile_id())


# ── Profile-driven hard-constraint (spec) extraction (NEW-2) ──────────────────────────────────────
# The refresh/RAM/storage/weight/esports spec logic used to be hardcoded electronics literals here;
# it now lives in the StoreProfile slots so this module is vertical-blind. A vertical with no rules
# extracts no specs (no GPU/refresh bleed into pharmacy/fashion).
@lru_cache(maxsize=8)
def _hard_constraint_rules_for(profile_id: str) -> tuple:
    from src.app.platform.store_profile import profile_slot
    raw = profile_slot("hard_constraint_rules", profile_id=profile_id, default=None)
    rules = []
    if isinstance(raw, list):
        for r in raw:
            if not isinstance(r, dict):
                continue
            pat, key = r.get("pattern"), str(r.get("key") or "")
            if not pat or not key:
                continue
            try:
                cpat = re.compile(pat, re.I)
            except re.error:
                continue
            rules.append({"re": cpat, "key": key, "cast": str(r.get("cast") or "int"),
                          "group": int(r.get("group", 1)), "multiplier": r.get("multiplier")})
    return tuple(rules)


@lru_cache(maxsize=8)
def _use_case_spec_implications_for(profile_id: str) -> tuple:
    from src.app.platform.store_profile import profile_slot
    raw = profile_slot("use_case_spec_implications", profile_id=profile_id, default=None)
    imps = []
    if isinstance(raw, list):
        for r in raw:
            if not isinstance(r, dict):
                continue
            pat, key = r.get("pattern"), str(r.get("key") or "")
            if not pat or not key:
                continue
            try:
                cpat = re.compile(pat, re.I)
            except re.error:
                continue
            imps.append({"use_case": str(r.get("use_case") or ""), "re": cpat, "key": key,
                         "value": r.get("value"), "mode": str(r.get("mode") or "set")})
    return tuple(imps)


@lru_cache(maxsize=8)
def _portable_weight_for(profile_id: str) -> Optional[float]:
    from src.app.platform.store_profile import profile_slot
    w = profile_slot("portable_weight_kg_max", profile_id=profile_id, default=None)
    if w is None:
        return None
    try:
        return float(w)
    except (TypeError, ValueError):
        return None


def _active_hard_constraint_rules() -> tuple:
    from src.app.platform.store_profile import active_profile_id
    return _hard_constraint_rules_for(active_profile_id())


def _active_use_case_spec_implications() -> tuple:
    from src.app.platform.store_profile import active_profile_id
    return _use_case_spec_implications_for(active_profile_id())


def _active_portable_weight() -> Optional[float]:
    from src.app.platform.store_profile import active_profile_id
    return _portable_weight_for(active_profile_id())


def reset_cache() -> None:
    """Clear the per-profile decomposer caches (test isolation / profile reload)."""
    for fn in (_use_case_patterns_for, _dgpu_use_cases_for, _portable_re_for,
               _hard_constraint_rules_for, _use_case_spec_implications_for, _portable_weight_for):
        try:
            fn.cache_clear()
        except Exception:
            pass


@dataclass
class SubQuestion:
    """One atomic ask inside a compound query ("…uni work? is $1400 enough?")."""
    text: str
    intent: str
    use_cases: List[str] = field(default_factory=list)
    hard_constraints: Dict[str, Any] = field(default_factory=dict)
    comparison_subjects: List[str] = field(default_factory=list)
    answer_without_products: bool = False
    is_budget_question: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "text": self.text,
            "intent": self.intent,
            "use_cases": self.use_cases,
            "hard_constraints": self.hard_constraints,
            "comparison_subjects": self.comparison_subjects,
            "answer_without_products": self.answer_without_products,
            "is_budget_question": self.is_budget_question,
        }


@dataclass
class QueryPlan:
    query: str
    intent: str
    use_cases: List[str] = field(default_factory=list)
    is_multi_intent: bool = False
    needs_dedicated_gpu: bool = False
    hard_constraints: Dict[str, Any] = field(default_factory=dict)
    comparison_subjects: List[str] = field(default_factory=list)
    category: Optional[str] = None
    answer_without_products: bool = False  # comparison/knowledge → conceptual answer ok
    sub_questions: List[SubQuestion] = field(default_factory=list)  # compound decomposition
    is_compound: bool = False  # ≥2 distinct sub-questions
    # Image trust state — part of the plan so downstream narration/routing can describe what the
    # system actually did with the upload. has_image is known at decompose time; image_relevance is
    # set by the caller AFTER CV triage ("in_domain" | "off_topic"), so off-domain uploads never get
    # narrated as "based on the product in your photo".
    has_image: bool = False
    image_relevance: Optional[str] = None
    # Budget surfaced INTO the plan (agnostic numeric parse — no vertical literals) so the top-level
    # decomposition is self-describing and downstream needn't re-derive the band to route.
    budget_min: Optional[int] = None
    budget_max: Optional[int] = None
    # Bulk/B2B quantity ("10 laptops") so downstream availability/fulfilment can reason about it.
    quantity: Optional[int] = None
    # Availability horizon in days ("in 4 weeks" → 28) for the fulfilment/lead-time answer (Step 3b).
    availability_horizon_days: Optional[int] = None
    # Negation/exclusion terms ("but not Apple", "without a touchscreen") — agnostic spans matched
    # against product DATA (brand/name/category) downstream. Fail-safe: a term that matches no product
    # filters nothing, and the search category itself is never excluded.
    exclusions: List[str] = field(default_factory=list)
    # Deterministic 0..1 confidence that the rules parsed this query well (more extracted signals →
    # higher). Drives WHEN the LLM-planner fallback is worth invoking, and is useful telemetry. Agnostic.
    decomposition_confidence: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "intent": self.intent,
            "use_cases": self.use_cases,
            "is_multi_intent": self.is_multi_intent,
            "needs_dedicated_gpu": self.needs_dedicated_gpu,
            "hard_constraints": self.hard_constraints,
            "comparison_subjects": self.comparison_subjects,
            "category": self.category,
            "answer_without_products": self.answer_without_products,
            "is_compound": self.is_compound,
            "sub_questions": [sq.to_dict() for sq in self.sub_questions],
            "has_image": self.has_image,
            "image_relevance": self.image_relevance,
            "budget_min": self.budget_min,
            "budget_max": self.budget_max,
            "quantity": self.quantity,
            "availability_horizon_days": self.availability_horizon_days,
            "exclusions": self.exclusions,
            "decomposition_confidence": self.decomposition_confidence,
        }


def _gpu_prefixes() -> List[str]:
    """GPU model-prefix tokens for the ACTIVE vertical, sourced from its ``gpu_prefixes`` profile
    slot. Empty for verticals that have none — so GPU-hint detection never bleeds discrete-GPU terms
    into pharmacy/fashion. profile_slot is defensive (never raises) → no try/except (off the ratchet)."""
    from src.app.platform.store_profile import profile_slot
    p = profile_slot("gpu_prefixes", default=None)
    return [str(x).strip().lower() for x in p if str(x).strip()] if isinstance(p, list) else []


# Budget amount: comma-grouped (1,600 / 12,000) OR plain 3-6 digits. Strip commas when parsing.
_BUDGET_NUM = r"(\d{1,3}(?:,\d{3})+|\d{3,6})"


def _budget_int(s: str) -> Optional[int]:
    try:
        v = int(str(s).replace(",", ""))
    except (TypeError, ValueError):
        return None
    return v if 50 < v <= 100000 else None


def _extract_budget_range(q: str) -> tuple[Optional[int], Optional[int]]:
    """Agnostic numeric budget parse → (min, max). Pure numbers + currency symbols, NO vertical
    literals, so it is valid for any store. Handles comma-formatted amounts ("$1,600"). Surfaced into
    QueryPlan.budget_min/max."""
    ql = str(q or "").lower()
    rng = re.search(r"[\$€£]?\s*" + _BUDGET_NUM + r"\s*(?:to|and|-|–|—)\s*[\$€£]?\s*" + _BUDGET_NUM + r"\b", ql)
    if rng:
        lo, hi = _budget_int(rng.group(1)), _budget_int(rng.group(2))
        if lo is not None and hi is not None and lo < hi:
            return lo, hi
    m = re.search(r"\b(?:under|below|max(?:imum)?|up\s*to|less\s*than|within)\s*[\$€£]?\s*" + _BUDGET_NUM + r"\b", ql) \
        or re.search(r"[\$€£]\s*" + _BUDGET_NUM + r"\b", ql)
    if m:
        v = _budget_int(m.group(1))
        if v is not None:
            return None, v
    m = re.search(r"\b(?:over|above|at\s*least|more\s*than|starting\s*at)\s*[\$€£]?\s*" + _BUDGET_NUM + r"\b", ql)
    if m:
        v = _budget_int(m.group(1))
        if v is not None:
            return v, None
    # Bare budget anchor: "budget is 1600", "budget of 1600", "budget 1600" (no $/keyword) → ceiling.
    m = re.search(r"\bbudget(?:\s*(?:is|of|:|=|around|about|~))?\s*[\$€£]?\s*" + _BUDGET_NUM + r"\b", ql)
    if m:
        v = _budget_int(m.group(1))
        if v is not None:
            return None, v
    return None, None


_QTY_STOP_NOUNS = {
    "weeks", "week", "days", "day", "months", "month", "years", "year", "hours", "hour",
    "minutes", "mins", "dollars", "bucks", "options", "results", "matches", "ones", "items",
    "products", "things", "models", "specs", "reviews",
    # spec UNITS that follow a number as a spec, never a bulk quantity (refresh-rate, RAM/storage
    # sizes, screen size, weight, etc.) — so a spec value is never read as an order quantity.
    "fps", "hz", "ghz", "mhz", "khz", "nits", "wh", "mah", "mp", "dpi", "ppi", "rpm",
    "kg", "kgs", "lb", "lbs", "mm", "cm", "inch", "inches", "gb", "tb", "mb", "kb",
    "w", "watts", "v", "volts", "ms", "cores", "core", "ghz", "k",
}


def _extract_quantity(q: str) -> Optional[int]:
    """Agnostic bulk-quantity parse: 'N <…adjectives…> <plural noun>' (e.g. '10 gaming laptops',
    '10 new laptops', '25 units'). Scans the few words AFTER the number for the first plural/unit
    noun, skipping adjectives ('gaming', 'business', 'new'). Stops at a time/currency word so
    '4 weeks' / 'in 28 days' are NEVER read as a quantity. Vertical-blind (pure number + plural noun)."""
    ql = str(q or "").lower()
    for m in re.finditer(rf"\b(\d{{1,4}}|{_NUMBER_WORD_ALT})\s+(.{{0,40}})", ql):
        n = _token_to_int(m.group(1))
        if n is None or not (1 < n <= 9999):
            continue
        for w in re.findall(r"[a-z]+", m.group(2))[:4]:
            if w in _QTY_STOP_NOUNS:
                break  # time/currency/filler immediately after the number → not a quantity
            if (w.endswith("s") and len(w) >= 3) or w in ("units", "pcs", "pieces"):
                return n
    return None


# ── Negation / exclusion ("laptop but not Apple", "without a touchscreen", "no refurbished") ──
# Agnostic grammar only: detect a negation cue, capture the short term it negates. Vertical-blind —
# the captured term is matched against product DATA (brand/name/category) downstream, NEVER against
# hardcoded brand literals here. Fail-safe by construction: a term that matches no product filters
# nothing, so over-capture is harmless; the search category itself is guarded out (never excluded).
_NEG_CUES_RE = re.compile(
    r"(?:\bwithout\b|\bexcluding\b|\bexcept(?:\s+for)?\b|\bother\s+than\b|\banything\s+but\b"
    r"|\bbut\s+not\b|\band\s+not\b"
    r"|\bdo(?:es)?(?:\s+not|n['’o]?t)\s+(?:want|need|like)\b"
    r"|\bavoid\b|\bskip\b|\brather\s+not\b"
    r"|\bnot\b|\bno\b)",
    re.IGNORECASE,
)
# Immediately-following tokens that mean the cue is a comparative/idiom/uncertainty phrase, NOT a
# product exclusion ("no more than $X", "not sure", "no rush") → skip that cue.
_NEG_SKIP_NEXT = {
    "more", "less", "fewer", "longer", "shorter", "bigger", "smaller", "older", "newer", "greater",
    "than", "sure", "idea", "problem", "problems", "worries", "worry", "rush", "preference",
    "preferences", "budget", "matter", "doubt", "way", "thanks", "really", "too", "much", "if",
    "when", "biggie", "clue", "issue", "issues", "limit", "max", "maximum", "minimum",
    # verbs/aux after a negation cue mean it's a statement ("I have not SET a budget", "haven't
    # GOT one"), not a product exclusion → skip so they don't become junk exclusion terms.
    "set", "got", "get", "have", "has", "had", "decided", "chosen", "picked", "settled",
    "figured", "made", "found", "thought", "planned", "fixed", "determined", "really",
}
# Generic shopping nouns that must never become an exclusion (would nuke the whole result set).
_NEG_STOP_TERMS = {
    "one", "ones", "option", "options", "product", "products", "item", "items", "model", "models",
    "thing", "things", "something", "anything", "stuff", "brand", "brands", "kind", "type", "types",
}
# Function words / new-clause markers that END the whole exclusion span.
_NEG_HARD_STOP = {
    "but", "with", "for", "that", "which", "under", "over", "below", "above", "around", "about",
    "budget", "to", "in", "on", "at", "of", "is", "are", "please", "thanks", "though", "however",
    "plus", "also", "because", "since", "while", "so", "not", "no", "without", "never",
}
# Soft separators between SIBLING exclusions ("not Apple or Dell" → ["apple", "dell"]).
_NEG_SOFT_SEP = {"or", "and", "nor"}
_NEG_LEAD_ARTICLES = {"a", "an", "the", "any", "some", "my", "your", "their", "this", "that"}


def _extract_exclusions(q: str, category: Optional[str] = None) -> List[str]:
    """Pull short negated terms from the query (agnostic). Handles sibling alternatives joined by
    or/and ("not Apple or Dell"). Returns a deduped, lowercased list. Fail-safe by construction."""
    ql = str(q or "").lower()
    if not ql:
        return []
    cat = (category or "").strip().lower()
    cat_forms = {cat, cat.rstrip("s"), cat + "s"} if cat else set()
    out: List[str] = []
    seen: set = set()
    for m in _NEG_CUES_RE.finditer(ql):
        words = re.findall(r"[a-z0-9][a-z0-9'’+-]*", ql[m.end():])
        i = 0
        while i < len(words) and words[i] in _NEG_LEAD_ARTICLES:
            i += 1
        if i >= len(words) or words[i] in _NEG_SKIP_NEXT:
            continue
        terms_here: List[str] = []
        cur: List[str] = []
        for w in words[i:i + 8]:
            if w in _NEG_HARD_STOP:
                break
            if w in _NEG_SOFT_SEP:
                if cur:
                    terms_here.append(" ".join(cur)); cur = []
                continue
            if w in _NEG_LEAD_ARTICLES and not cur:
                continue  # strip a leading article on each sibling
            cur.append(w)
            if len(cur) >= 3:
                terms_here.append(" ".join(cur)); cur = []
        if cur:
            terms_here.append(" ".join(cur))
        for term in terms_here:
            term = term.strip()
            if len(term) < 2 or term in _NEG_STOP_TERMS or term in cat_forms or term in _NEG_SKIP_NEXT:
                continue
            if term not in seen:
                seen.add(term)
                out.append(term)
    return out[:5]


def _extract_comparison_subjects(q: str) -> List[str]:
    """Pull the two things being compared (e.g. two model names, two products)."""
    ql = q
    subjects: List[str] = []
    # "between X and Y"
    m = re.search(r"between\s+(.+?)\s+and\s+(.+?)(?:\?|$|\sfor\b|\sgaming\b)", ql, re.I)
    if m:
        subjects = [m.group(1).strip(), m.group(2).strip()]
    else:
        m = re.search(r"(.+?)\s+(?:vs\.?|versus|or)\s+(.+?)(?:\?|$|\sfor\b)", ql, re.I)
        if m:
            subjects = [m.group(1).strip(), m.group(2).strip()]
    # Trim leading filler
    cleaned = []
    for s in subjects:
        s = re.sub(r"^(the|a|an|what'?s|difference|is|which)\s+", "", s, flags=re.I).strip()
        if s and len(s) < 60:
            cleaned.append(s)
    return cleaned[:2]


def _extract_hard_constraints(q: str, use_cases: List[str]) -> Dict[str, Any]:
    """Turn natural-language spec phrases into HARD filters. Vertical-blind: the spec patterns,
    units, and implied floors all come from the active StoreProfile slots (hard_constraint_rules /
    use_case_spec_implications / portable_weight_kg_max), so electronics carries its refresh/RAM/
    storage rules in its profile and a pharmacy/fashion store contributes its own (or none)."""
    out: Dict[str, Any] = {}
    ql = q.lower()
    # 1) Profile spec rules (refresh, RAM, storage, weight-under-N…).
    for rule in _active_hard_constraint_rules():
        m = rule["re"].search(ql)
        if not m:
            continue
        try:
            raw = m.group(rule["group"])
        except IndexError:
            continue
        if raw is None:
            continue
        val: Any = float(raw) if rule["cast"] == "float" else int(raw)
        mult = rule.get("multiplier")
        if mult:
            val = int(val * int(mult))
        out[rule["key"]] = val
    # 2) Portability → weight cap (setdefault so an explicit 'under N kg' rule above always wins).
    if _active_portable_re().search(ql):
        w = _active_portable_weight()
        if w is not None:
            out.setdefault("weight_kg_max", w)
    # 3) Explicit GPU model hint — prefixes come from the active StoreProfile, so a non-GPU vertical
    # adds none and electronics stays byte-identical (its profile carries the model prefixes).
    _gpre = _gpu_prefixes()
    if _gpre:
        _gpu_pat = "|".join(re.escape(p) for p in _gpre)
        m = re.search(rf"\b({_gpu_pat})\s*(\d{{3,4}})\b", ql)
        if m:
            out["gpu_model_hint"] = f"{m.group(1)} {m.group(2)}"
    # 4) Dedicated-GPU requirement from use cases (dgpu set derived from the profile).
    if any(uc in _active_dgpu_use_cases() for uc in use_cases):
        out["must_have_dedicated_gpu"] = True
    # 5) Profile use-case spec implications (e.g. competitive gaming → a high refresh floor).
    for imp in _active_use_case_spec_implications():
        if imp["use_case"] in use_cases and imp["re"].search(ql):
            if imp["mode"] == "setdefault":
                out.setdefault(imp["key"], imp["value"])
            else:
                out[imp["key"]] = imp["value"]
    return out


def _decomposition_confidence(plan: "QueryPlan", q: str) -> float:
    """Deterministic 0..1 confidence that the rules parsed this query well — the count of structured
    signals they pulled out (category, use-cases, budget, constraints, a specific intent…). Used to
    decide when the LLM-planner fallback is worth invoking and as routing telemetry. Vertical-blind."""
    words = len(str(q or "").split())
    if words == 0:
        return 0.0
    score = 0.0
    if plan.category:
        score += 0.32
    if plan.use_cases:
        score += 0.30
    if plan.budget_min is not None or plan.budget_max is not None:
        score += 0.16
    if plan.hard_constraints:
        score += 0.10
    if plan.comparison_subjects:
        score += 0.10
    if plan.intent in (INTENT_COMPARISON, INTENT_KNOWLEDGE, INTENT_AVAILABILITY, INTENT_SUPPORT, INTENT_MULTI):
        score += 0.10
    if plan.quantity is not None or plan.availability_horizon_days is not None:
        score += 0.05
    # A short query that still resolved a category/use-case is confidently simple (rules nailed it).
    if words < 4 and (plan.category or plan.use_cases):
        score += 0.10
    return round(min(1.0, score), 3)


def _classify_clause(q: str) -> SubQuestion:
    """Classify ONE clause/segment into a SubQuestion (intent + extracted bits).
    Shared by the top-level plan and each compound sub-question so they agree."""
    use_cases = [uc for uc, pat in _active_use_case_patterns().items() if pat.search(q)]
    hc = _extract_hard_constraints(q, use_cases)
    budget_q = is_budget_question(q)
    listy = bool(_PRODUCT_LISTY_RE.search(q))
    sq = SubQuestion(text=q, intent=INTENT_PRODUCT_SEARCH, use_cases=use_cases,
                     hard_constraints=hc, is_budget_question=budget_q)
    if _SUPPORT_RE.search(q):
        sq.intent = INTENT_SUPPORT
    elif _EXPLAIN_REF_RE.search(q) and not listy:
        # Rationale about the existing shortlist — answer conceptually, don't re-search.
        sq.intent = INTENT_KNOWLEDGE
        sq.answer_without_products = True
    elif _COMPARISON_RE.search(q) and not listy:
        sq.intent = INTENT_COMPARISON
        sq.comparison_subjects = _extract_comparison_subjects(q)
        sq.answer_without_products = True
    elif _AVAILABILITY_RE.search(q) and not listy:
        # Fulfilment/lead-time ask — a distinct intent so a compound "products + can you deliver?"
        # splits correctly. NOT answer_without_products: it's a question ABOUT products.
        sq.intent = INTENT_AVAILABILITY
    elif _KNOWLEDGE_RE.search(q) and not listy and not budget_q:
        sq.intent = INTENT_KNOWLEDGE
        sq.answer_without_products = True
    elif len(use_cases) >= 2:
        sq.intent = INTENT_MULTI
    else:
        sq.intent = INTENT_PRODUCT_SEARCH
    return sq


# A trailing conjunct is its OWN clause (worth splitting on " and "/" also ") only when
# it stands alone as a question/request — a budget-sufficiency, knowledge, or comparison
# question, OR a clause that OPENS with an interrogative/listy marker ("which laptop…",
# "show me…"). This splits genuine compounds while NOT fragmenting single product
# requests ("laptop for gaming and under 1500") or use-case lists ("gaming and video
# editing") whose conjuncts don't open with such a marker.
_CLAUSE_START_RE = re.compile(
    r"^(which|what'?s?|how|is|are|do|does|can|should|would|"
    r"show me|find me|recommend|suggest|i need|i want|looking for)\b",
    re.IGNORECASE,
)


def _is_independent_clause(seg: str) -> bool:
    s = seg.strip()
    if not s:
        return False
    if is_budget_question(s):
        return True
    if len(s.split()) < 2:
        return False
    if _KNOWLEDGE_RE.search(s) or _COMPARISON_RE.search(s) or _AVAILABILITY_RE.search(s):
        return True
    return bool(_CLAUSE_START_RE.match(s) and len(s.split()) >= 3)


def _segment_query(q: str) -> List[str]:
    """Split a compound query into atomic clauses. High-precision: splits on strong
    boundaries (? ; sentence .) always, and on ' and '/' also '/' plus only when the
    trailing conjunct is an independent question of a different shape."""
    # 1) strong boundaries
    raw = [p for p in re.split(r"[?;]+|(?<=[a-z0-9])\.\s+", q) if p and p.strip()]
    segments: List[str] = []
    for part in raw:
        part = part.strip()
        # 2) conservative conjunction split (left-to-right, one level)
        pieces = re.split(r"\s+(?:and also|and|also|plus|,\s*and|,\s*also)\s+", part, flags=re.IGNORECASE)
        if len(pieces) >= 2 and any(_is_independent_clause(pc) for pc in pieces[1:]):
            # keep the head with everything up to the first independent conjunct merged,
            # then each independent conjunct as its own segment.
            head = pieces[0].strip()
            buf = head
            for pc in pieces[1:]:
                if _is_independent_clause(pc):
                    if buf.strip():
                        segments.append(buf.strip())
                    buf = pc.strip()
                else:
                    buf = (buf + " and " + pc).strip()
            if buf.strip():
                segments.append(buf.strip())
        else:
            segments.append(part)
    # 3) clean + dedup
    out: List[str] = []
    seen = set()
    for s in segments:
        s2 = s.strip(" ,.")
        if not s2:
            continue
        if len(s2.split()) < 2 and not is_budget_question(s2):
            continue
        key = s2.lower()
        if key not in seen:
            seen.add(key)
            out.append(s2)
    return out


def decompose(query: Optional[str], *, has_image: bool = False) -> QueryPlan:
    """Decompose a raw query into a structured plan, including compound sub-questions.
    Never raises. The top-level fields stay backward-compatible (classified from the
    WHOLE query); ``sub_questions``/``is_compound`` are additive."""
    q = str(query or "").strip()
    plan = QueryPlan(query=q, intent=INTENT_PRODUCT_SEARCH)
    plan.has_image = bool(has_image)  # image_relevance is set by the caller after CV triage
    if not q:
        return plan
    try:
        plan.category = coarse_product_category(q)
        plan.budget_min, plan.budget_max = _extract_budget_range(q)
        plan.quantity = _extract_quantity(q)
        plan.availability_horizon_days = _extract_availability_horizon(q)
        # Top-level classification (whole query) — preserves existing behaviour.
        top = _classify_clause(q)
        plan.intent = top.intent
        plan.use_cases = top.use_cases
        plan.needs_dedicated_gpu = any(uc in _active_dgpu_use_cases() for uc in plan.use_cases)
        plan.hard_constraints = top.hard_constraints
        plan.comparison_subjects = top.comparison_subjects
        plan.answer_without_products = top.answer_without_products
        if plan.intent == INTENT_MULTI:
            plan.is_multi_intent = True

        # Compound decomposition — split into sub-questions and classify each.
        segments = _segment_query(q)
        if len(segments) >= 2:
            subs = [_classify_clause(s) for s in segments]
            distinct_intents = {s.intent for s in subs}
            # Treat as compound only when the split produced genuinely different asks
            # (e.g. product_search + budget question, or knowledge + product_search) —
            # not two near-identical product clauses.
            has_qna = any(s.answer_without_products or s.is_budget_question for s in subs)
            if len(distinct_intents) >= 2 or has_qna:
                plan.sub_questions = subs
                plan.is_compound = True
                plan.is_multi_intent = True

        # Compound→primary: when the whole-query landed on a non-product intent (knowledge/comparison)
        # but a product-search sub-question exists, the user's PRIMARY ask is the product — don't let
        # an accessory/knowledge clause ("do I need an external hard drive?") hijack category/intent
        # into a prose-only answer that surfaces no products.
        if plan.is_compound and plan.intent in (INTENT_KNOWLEDGE, INTENT_COMPARISON, INTENT_AVAILABILITY):
            prod_subs = [s for s in plan.sub_questions if s.intent in (INTENT_PRODUCT_SEARCH, INTENT_MULTI)]
            if prod_subs:
                plan.intent = INTENT_PRODUCT_SEARCH
                plan.answer_without_products = False
                ucs: List[str] = []
                for s in prod_subs:
                    for uc in s.use_cases:
                        if uc not in ucs:
                            ucs.append(uc)
                if ucs:
                    plan.use_cases = ucs
                    plan.needs_dedicated_gpu = any(uc in _active_dgpu_use_cases() for uc in ucs)
                # category from a PRODUCT clause only — never the accessory/knowledge clause.
                new_cat = None
                for s in prod_subs:
                    c = coarse_product_category(s.text)
                    if c:
                        new_cat = c
                        break
                plan.category = new_cat

        # Availability RIDER guard: "…laptops…, can you deliver in 4 weeks?" must NOT flip the whole
        # turn to availability-only when product signals exist (category / use-case / quantity). Keep
        # product primary and carry availability_horizon_days for the fulfilment answer (Step 3b).
        # Pure-availability queries (no product signals) stay INTENT_AVAILABILITY.
        if plan.intent == INTENT_AVAILABILITY and (plan.category or plan.use_cases or plan.quantity):
            plan.intent = INTENT_PRODUCT_SEARCH
            plan.answer_without_products = False

        # Negation/exclusion terms (after category is finalized, so the search category is guarded out).
        plan.exclusions = _extract_exclusions(q, plan.category)
        # Confidence is scored LAST — after every signal above is populated.
        plan.decomposition_confidence = _decomposition_confidence(plan, q)
    except Exception:
        # Fail safe: behave like a plain product search.
        plan.intent = INTENT_PRODUCT_SEARCH
    return plan
