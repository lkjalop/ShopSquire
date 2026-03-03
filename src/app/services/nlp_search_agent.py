"""NLP Search Agent — PEG-style constraint grammar, semantic slot filling, intent confidence.

Parses free-text shopping queries into structured slots that drive product search
and recommendations.  Handles:
  - Budget extraction (numbers, fuzzy phrases like "won't break the bank")
  - Negation tracking ("not ASUS", "no refurbished")
  - Spec extraction (RAM, GPU, storage, display, refresh rate)
  - Use-case & brand extraction
  - Session slot accumulation (merge new query with prior slots)
  - Intent confidence 0-1
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


# ── Fuzzy budget phrases → approximate (min, max) ranges ──
_BUDGET_PHRASES: List[Tuple[re.Pattern, Optional[int], Optional[int]]] = [
    (re.compile(r"\b(?:cheap|budget|affordable|won'?t break the bank|low[\s-]?cost)\b", re.I), None, 600),
    (re.compile(r"\b(?:mid[\s-]?range|moderate|reasonable)\b", re.I), 500, 1200),
    (re.compile(r"\b(?:premium|high[\s-]?end|top[\s-]?tier|money is no object|flagship)\b", re.I), 1200, None),
    (re.compile(r"\b(?:under|below|less than|max)\s*[\$£€]?\s*(\d[\d,]*)", re.I), None, None),  # dynamic
    (re.compile(r"\b(?:above|over|more than|at least|minimum)\s*[\$£€]?\s*(\d[\d,]*)", re.I), None, None),  # dynamic
    (re.compile(r"[\$£€]\s*(\d[\d,]*)\s*[-–to]+\s*[\$£€]?\s*(\d[\d,]*)", re.I), None, None),  # range
    (re.compile(r"(\d[\d,]*)\s*[-–to]+\s*(\d[\d,]*)\s*(?:dollar|buck|pound|euro|£|\$|€)", re.I), None, None),
    (re.compile(r"\b(?:around|about|roughly|approximately|~)\s*[\$£€]?\s*(\d[\d,]*)", re.I), None, None),
]

# ── Spec patterns ──
_SPEC_PATTERNS = {
    "ram_gb": re.compile(r"(\d+)\s*(?:gb|gig)\s*(?:ram|memory)|\b(?:ram|memory)\s*(?:of\s*)?(\d+)\s*(?:gb|gig)", re.I),
    "storage_gb": re.compile(r"(\d+)\s*(?:gb|tb)\s*(?:ssd|hdd|nvme|storage|drive)|(?:ssd|storage)\s*(?:of\s*)?(\d+)\s*(?:gb|tb)", re.I),
    "display_inches": re.compile(r"(\d{2}(?:\.\d)?)\s*[\"\u2033]?\s*(?:inch|screen|display)", re.I),
    "refresh_hz": re.compile(r"(\d{2,3})\s*(?:hz|hertz)\s*(?:refresh|display|screen)?", re.I),
    "gpu_vram_gb": re.compile(r"(\d+)\s*(?:gb|gig)\s*(?:vram|video\s*(?:memory|ram))", re.I),
}

# ── Negation phrases ──
_NEGATION_PATTERN = re.compile(
    r"(?:not?|no|don'?t want|avoid|exclude|without|never)\s+([A-Za-z0-9][\w\s]{0,30}?)(?:\s*[,;.]|\s+(?:and|or|but)|$)",
    re.I,
)

# ── Brand detection ──
_KNOWN_BRANDS = [
    "lenovo", "dell", "hp", "asus", "acer", "apple", "msi", "samsung",
    "razer", "microsoft", "lg", "huawei", "honor", "gigabyte", "toshiba",
    "fujitsu", "panasonic", "alienware", "thinkpad",
]

# ── Intent keywords → (intent, base_confidence) ──
_INTENT_MAP: List[Tuple[re.Pattern, str, float]] = [
    (re.compile(r"\b(?:recommend|suggest|find|looking for|need|want|help me choose|which)\b", re.I), "recommend", 0.7),
    (re.compile(r"\b(?:compare|vs|versus|difference|better)\b", re.I), "compare", 0.8),
    (re.compile(r"\b(?:return|refund|send back|exchange)\b", re.I), "return", 0.9),
    (re.compile(r"\b(?:broken|defective|problem|issue|not working|fault)\b", re.I), "support", 0.85),
    (re.compile(r"\b(?:track|where is|shipping|delivery|status)\b", re.I), "track_order", 0.9),
    (re.compile(r"\b(?:price|cost|how much)\b", re.I), "price_check", 0.6),
]


@dataclass
class ParsedQuery:
    """Structured output from NLP search agent."""
    raw_query: str
    intent: str = "recommend"
    intent_confidence: float = 0.5
    budget_min: Optional[int] = None
    budget_max: Optional[int] = None
    specs: Dict[str, Any] = field(default_factory=dict)
    brands_positive: List[str] = field(default_factory=list)
    brands_negative: List[str] = field(default_factory=list)
    negations: List[str] = field(default_factory=list)
    use_case_hints: List[str] = field(default_factory=list)
    mention_count: int = 0  # how many constraint signals found


def _parse_number(s: str) -> int:
    """Parse a number string, handling commas."""
    return int(s.replace(",", ""))


def parse_query(query: str) -> ParsedQuery:
    """Parse a free-text shopping query into structured constraints."""
    result = ParsedQuery(raw_query=query)
    q = (query or "").strip()
    if not q:
        return result

    signals = 0

    # ── Intent detection ──
    best_intent = "recommend"
    best_intent_conf = 0.3
    for pattern, intent, conf in _INTENT_MAP:
        if pattern.search(q):
            if conf > best_intent_conf:
                best_intent = intent
                best_intent_conf = conf
    result.intent = best_intent
    result.intent_confidence = best_intent_conf

    # ── Budget extraction ──
    ql = q.lower()
    # Explicit numeric patterns first
    # Range: $500-$1000
    range_m = re.search(r"[\$£€]\s*(\d[\d,]*)\s*[-–to]+\s*[\$£€]?\s*(\d[\d,]*)", q, re.I)
    if not range_m:
        range_m = re.search(r"(\d[\d,]*)\s*[-–to]+\s*(\d[\d,]*)\s*(?:dollar|buck|pound|euro|£|\$|€)", q, re.I)
    if range_m:
        result.budget_min = _parse_number(range_m.group(1))
        result.budget_max = _parse_number(range_m.group(2))
        signals += 1
    else:
        # Under/below X
        under_m = re.search(r"\b(?:under|below|less than|max|up to)\s*[\$£€]?\s*(\d[\d,]*)", q, re.I)
        if under_m:
            result.budget_max = _parse_number(under_m.group(1))
            signals += 1
        # Above/over X
        above_m = re.search(r"\b(?:above|over|more than|at least|minimum)\s*[\$£€]?\s*(\d[\d,]*)", q, re.I)
        if above_m:
            result.budget_min = _parse_number(above_m.group(1))
            signals += 1
        # Around X
        around_m = re.search(r"\b(?:around|about|roughly|approximately|~)\s*[\$£€]?\s*(\d[\d,]*)", q, re.I)
        if around_m:
            val = _parse_number(around_m.group(1))
            result.budget_min = int(val * 0.8)
            result.budget_max = int(val * 1.2)
            signals += 1
        # Fuzzy phrases
        if result.budget_min is None and result.budget_max is None:
            for pat, fmin, fmax in _BUDGET_PHRASES[:3]:
                if pat.search(q):
                    result.budget_min = fmin
                    result.budget_max = fmax
                    signals += 1
                    break

    # ── Spec extraction ──
    for spec_key, pattern in _SPEC_PATTERNS.items():
        m = pattern.search(q)
        if m:
            val_str = m.group(1) or m.group(2)
            if val_str:
                val = int(val_str)
                # Convert TB to GB for storage
                if spec_key == "storage_gb" and "tb" in m.group(0).lower():
                    val *= 1024
                result.specs[spec_key] = val
                signals += 1

    # ── Negation tracking ──
    for neg_match in _NEGATION_PATTERN.finditer(q):
        neg_text = neg_match.group(1).strip().lower()
        # Check if negation targets a brand
        is_brand = False
        for brand in _KNOWN_BRANDS:
            if brand in neg_text:
                result.brands_negative.append(brand)
                is_brand = True
        if not is_brand and neg_text:
            result.negations.append(neg_text)
        signals += 1

    # ── Brand detection (positive) ──
    for brand in _KNOWN_BRANDS:
        if re.search(r"\b" + re.escape(brand) + r"\b", ql):
            if brand not in result.brands_negative:
                result.brands_positive.append(brand)
                signals += 1

    # ── Use-case hints ──
    uc_patterns = {
        "gaming": r"\bgam(?:ing|er|es)\b",
        "university": r"\b(?:university|college|student|study)\b",
        "office": r"\b(?:office|business|corporate|work\b)",
        "content_creation": r"\b(?:video edit|content|youtube|stream)\b",
        "programming": r"\b(?:program|develop|coding|software dev)",
        "design": r"\b(?:design|illustrat|graphic|photoshop)\b",
    }
    for uc_key, pat in uc_patterns.items():
        if re.search(pat, ql):
            result.use_case_hints.append(uc_key)
            signals += 1

    result.mention_count = signals
    # Boost intent confidence based on signal count
    if signals >= 3:
        result.intent_confidence = min(result.intent_confidence + 0.15, 1.0)
    elif signals >= 1:
        result.intent_confidence = min(result.intent_confidence + 0.05, 1.0)

    return result


def merge_slots(
    prior: ParsedQuery,
    new: ParsedQuery,
) -> ParsedQuery:
    """Accumulate slots across conversation turns.

    Later values override earlier values for the same slot, except lists
    which append unique items.
    """
    merged = ParsedQuery(raw_query=new.raw_query)
    merged.intent = new.intent if new.intent_confidence >= prior.intent_confidence else prior.intent
    merged.intent_confidence = max(prior.intent_confidence, new.intent_confidence)

    # Budget: new overrides if set
    merged.budget_min = new.budget_min if new.budget_min is not None else prior.budget_min
    merged.budget_max = new.budget_max if new.budget_max is not None else prior.budget_max

    # Specs: deep merge, new overrides
    merged.specs = {**prior.specs, **new.specs}

    # Lists: unique union
    merged.brands_positive = list(dict.fromkeys(prior.brands_positive + new.brands_positive))
    merged.brands_negative = list(dict.fromkeys(prior.brands_negative + new.brands_negative))
    # Remove brands that are both positive and negative (negative wins)
    merged.brands_positive = [b for b in merged.brands_positive if b not in merged.brands_negative]
    merged.negations = list(dict.fromkeys(prior.negations + new.negations))
    merged.use_case_hints = list(dict.fromkeys(prior.use_case_hints + new.use_case_hints))

    merged.mention_count = prior.mention_count + new.mention_count

    return merged
