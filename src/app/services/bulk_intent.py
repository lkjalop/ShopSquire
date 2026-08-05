"""Bulk-quantity intent grammar (agnostic CORE) — "15 work laptops" → qty 15, for ANY vertical.

The twin of budget_grammar: one place that decides whether a number in buyer text is a UNIT COUNT
(vs a model number, a spec size, or money). Core knows only GENERIC unit nouns (units/items/pieces…);
the vertical's product nouns are INJECTED by the caller (the recommend adapter flattens the active
StoreProfile's ``category_keywords``), so "15 dresses" parses in a fashion store the day its profile
fills that slot — no core change.

Returned spans let the caller EXCISE the number from the retrieval text (a bare "15" left in the query
becomes a product-NAME token — matching "Dell 15" — and zeroes banded results; the original live bug).

Pure, no I/O. Guards (each one a real regression):
  * a number preceded by a NAME-like token is never a qty       ("dell 15 laptops")
  * a spec filler between number and noun is never a qty        ("15 inch laptops")
  * out-of-range counts (>max / zero / negative) are refused via absurd_quantity_span, honestly.
"""
from __future__ import annotations

import re
from functools import lru_cache
from typing import Iterable, Optional, Tuple

MAX_SOURCEABLE_QTY = 1000

# function words that may sit before a quantity; an ALPHA token not in this set means the number is
# part of a product name ("dell 15 laptops") — never a qty.
_QTY_PRECEDING_OK = frozenset({
    "with", "need", "needs", "want", "wants", "get", "buy", "order", "purchase", "about", "around",
    "roughly", "approx", "approximately", "so", "for", "of", "the", "some", "extra", "another", "me",
    "us", "like", "say", "grab", "source", "and", "plus", "have", "getting", "buying", "ordering",
    # Catalog commands before a count: "suggest 10 suitable laptops" is a quantity request,
    # while the existing name-token guard still rejects product names such as "Dell 15 laptops".
    "suggest", "recommend", "show", "find", "list", "compare",
    "quote", "rfq", "source",
    # amendment phrasings — "make it 12 units", "change that to 10", "just 5" (all function words;
    # without these the name-token guard built for "dell 15" wrongly rejected fresh amendments,
    # letting a REMEMBERED qty beat a fresh one — caught live by the T3 memory probe)
    "it", "them", "that", "this", "to", "make", "just", "only", "at", "least", "take", "do",
    "set", "change", "reduce", "drop", "lower",
})
# a word between the number and the unit-noun that means the number is a SPEC, not a quantity.
_QTY_SPEC_FILLERS = re.compile(r"\b(?:inch(?:es)?|in|\"|gb|tb|mb|hz|ghz|kg|lb|nits?|core|gen)\b", re.I)
# vertical-blind unit nouns — real product nouns are injected per-vertical by the caller.
_GENERIC_UNIT_NOUNS = (
    "units?",
    "items?",
    "pieces?",
    "pcs",
    # A beneficiary count is a common product-agnostic way to state order quantity:
    # "laptops for 20 students" and "seats for 12 users". These nouns establish
    # the magnitude of the request without encoding a product category or capability.
    "people",
    "persons?",
    "students?",
    "employees?",
    "users?",
    "staff",
    r"team\s+members?",
    r"of\s+(?:them|these|those)",
)
_NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "fifteen": 15, "twenty": 20,
    "twenty-five": 25, "thirty": 30, "forty": 40, "fifty": 50,
}


@lru_cache(maxsize=32)
def _noun_alternation(extra_nouns: Tuple[str, ...]) -> str:
    parts = list(_GENERIC_UNIT_NOUNS)
    for n in extra_nouns:
        tok = re.escape(str(n).strip().lower())
        if tok:
            parts.append(tok + r"(?:s|es)?" if not tok.endswith("s") else tok)
    return "|".join(parts)


def _preceded_by_name_token(q: str, start: int) -> bool:
    before = q[:start].rstrip()
    prev = re.split(r"[^a-z0-9]+", before)[-1] if before else ""
    return bool(prev and prev.isalpha() and prev not in _QTY_PRECEDING_OK)


def extract_quantity_span(query: Optional[str], unit_nouns: Iterable[str] = ()) -> Optional[Tuple[int, str]]:
    """Quantity for bulk-order intent + the MATCHED NUMBER TEXT (so the caller can excise it).
    Handles 'qty: 15', '15x', '15 laptops', '15 work laptops' (≤2 filler words), '30 or so laptops',
    'need about 25'. Returns (qty, number_text) or None."""
    if not query:
        return None
    q = str(query).strip().lower()
    if not q:
        return None
    nouns = _noun_alternation(tuple(sorted({str(n).strip().lower() for n in unit_nouns if str(n).strip()})))

    def _looks_like_date(start: int, end: int) -> bool:
        """Keep delivery dates out of the consequential quantity slot.

        Procurement amendments commonly say ``need them by 25 September``. The broad
        ``need ... <number>`` fallback used to reinterpret that day-of-month as a new order
        quantity, silently shrinking an existing case.
        """
        before = q[max(0, start - 24):start]
        after = q[end:end + 16]
        month = (
            r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
            r"jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
        )
        return bool(
            re.search(r"\bby\s*$", before)
            or re.match(rf"\s*(?:st|nd|rd|th)?\s+{month}\b", after)
            or re.match(r"\s*[/.-]\s*\d{1,2}(?:\s*[/.-]\s*\d{2,4})?", after)
        )

    def _ok(m: "re.Match", *, check_fillers: bool = False) -> Optional[Tuple[int, str]]:
        # Never interpret a numeric suffix embedded in a SKU/model token as an
        # order count ("RGAM-0007 laptops" previously became seven laptops).
        # A real count is whitespace/delimiter separated; identifier punctuation
        # and adjacent alphanumerics keep the number inside product identity.
        start = m.start(1)
        end = m.end(1)
        if _looks_like_date(start, end):
            return None
        if start > 0 and (q[start - 1].isalnum() or q[start - 1] in "-_/."):
            return None
        if end < len(q) and (q[end].isalnum() or q[end] in "_/."):
            return None
        try:
            qty = int(m.group(1))
        except (TypeError, ValueError):
            return None
        if qty < 1 or qty > MAX_SOURCEABLE_QTY:
            return None
        if _preceded_by_name_token(q, m.start(1)):
            return None
        if check_fillers and _QTY_SPEC_FILLERS.search(m.group(2) or ""):
            return None
        return qty, m.group(1)

    m = re.search(r"\b(?:qty|quantity)\s*[:=#-]?\s*(\d{1,4})\b", q)
    if m:
        return _ok(m)
    m = re.search(r"\b(\d{1,4})\s*[x×]\b", q)
    if m:
        return _ok(m)
    # Hyphenated workload modifiers are still ordinary fillers ("20 game-development laptops").
    # The spec-filler guard below remains authoritative for "15-inch laptops" / "16GB laptops".
    m = re.search(rf"\b(\d{{1,4}})\s+((?:[a-z]+(?:[-\s]+)){{0,3}}?)(?:{nouns})\b", q)
    if m:
        r = _ok(m, check_fillers=True)
        if r:
            return r
    word_pattern = "|".join(
        re.escape(word) for word in sorted(_NUMBER_WORDS, key=len, reverse=True)
    )
    m = re.search(
        rf"\b({word_pattern})\s+((?:[a-z]+(?:[-\s]+)){{0,3}}?)(?:{nouns})\b",
        q,
    )
    if m:
        if not _preceded_by_name_token(q, m.start(1)):
            if not _QTY_SPEC_FILLERS.search(m.group(2) or ""):
                return _NUMBER_WORDS[m.group(1)], m.group(1)
    m = re.search(r"\b(?:need|want|get|buy|order|purchase|looking\s+for|help\s+with)\s+"
                  r"(?:about|around|roughly|approx\w*|maybe|some|say)?\s*(\d{1,4})\b", q)
    if m:
        return _ok(m)
    # Contextual amendments have an already-authorized subject, so no product noun is required.
    m = re.search(
        r"\b(?:make|set|change|reduce|drop|lower)(?:\s+(?:it|them|that|this|quantity|units?))?"
        r"\s+to\s+(\d{1,4})\b",
        q,
    )
    if m:
        return _ok(m)
    return None


def absurd_quantity_span(query: Optional[str], unit_nouns: Iterable[str] = (),
                         max_qty: int = MAX_SOURCEABLE_QTY) -> Optional[Tuple[int, str]]:
    """An out-of-range unit count the platform must REFUSE HONESTLY instead of silently degrading:
    > max_qty ('99999 laptops'), zero, or negative. Returns (count, number_text) or None."""
    if not query:
        return None
    q = str(query).strip().lower()
    nouns = _noun_alternation(tuple(sorted({str(n).strip().lower() for n in unit_nouns if str(n).strip()})))
    m = re.search(rf"(-?\d{{1,9}})\s+(?:[a-z]+\s+){{0,2}}?(?:{nouns})\b", q)
    if not m:
        m = re.search(r"\b(?:need|want|get|buy|order|purchase|give\s+me)\s+(?:about|around|roughly)?\s*(-?\d{4,9})\b", q)
    if not m:
        return None
    if _preceded_by_name_token(q, m.start(1)):
        return None  # a brand-prefixed number ("<brand> 4070 <noun>") is a model number, never a count
    try:
        n = int(m.group(1))
    except (TypeError, ValueError):
        return None
    if 1 <= n <= max_qty:
        return None  # a sane count — extract_quantity_span owns it
    return n, m.group(1)


def requires_full_procurement_path(
    plan: object,
    query: Optional[str],
    *,
    unit_nouns: Iterable[str] = (),
) -> bool:
    """Whether catalog-only retrieval lacks economics or availability context."""
    return bool(
        getattr(plan, "quantity", None)
        or extract_quantity_span(query, unit_nouns=unit_nouns)
        or getattr(plan, "availability_horizon_days", None)
    )
