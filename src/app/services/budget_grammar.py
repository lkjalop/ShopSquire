"""Budget grammar (agnostic CORE) — the ONE place a money budget is parsed from buyer text.

Five near-duplicate budget grammars grew across the stack (nlp_search_agent.parse_query,
query_decomposer._extract_budget_range, chat._extract_budget_bounds,
recommend._extract_explicit_budget_override, recommendations._extract_price_range), and every new
phrasing had to be fixed five times — "cut it to 1000 max" reached three of them before the LIVE one.
This module is the canonical grammar; the five call it FIRST and keep their local patterns only as
legacy fallback. Add a phrasing HERE once → every lane benefits.

Vertical-blind: pure numbers, currency symbols, and generic verbs — no product vocabulary. Pure function,
no DB, no network. Returns a BudgetParse or None (None = this grammar saw no budget; the caller may still
try its legacy patterns).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

# a number with optional commas/decimals and a k/m suffix ("1,600", "1.5k", "2k").
# Hardened against two real regressions: it cannot END on a comma and cannot be FOLLOWED by
# (comma+)digit — so "1400, maybe" never binds the 'm' as a millions suffix, and "under $1,500 in two
# weeks" cannot BACKTRACK to "$150"/"$1" to satisfy a later guard (the unit guard contains "in").
_NUM = r"(\d(?:[\d,]*\d)?(?:\.\d+)?)(?!,?\d)(?:\s*(k|m|grand)\b)?"
# a trailing measurement unit means the number is a SPEC, not money ("under 2 kg", "under 16 gb")
# NOTE: bare "in" is NOT in the guard — "under $1,500 in two weeks" is a budget + a deadline; real
# inch phrasings ("15 in") are < the 50-dollar floor every branch applies, so they can never become money.
_UNIT_GUARD = (r"(?!\s*(?:kg|kgs|lb|lbs|g|gb|tb|mb|kb|hz|ghz|mhz|khz|fps|inch|inches|cm|mm|w|"
               r"watts|wh|mah|mp|cores?|nits|ppi|dpi)\b)")
_CUR = r"[\$€£]"


@dataclass(frozen=True)
class BudgetParse:
    budget_min: Optional[int]
    budget_max: Optional[int]
    mode: str               # range | ceiling | floor | around | revision_down | per_unit

    @property
    def found(self) -> bool:
        return self.budget_min is not None or self.budget_max is not None


def _to_int(num: str, suffix: Optional[str]) -> Optional[int]:
    try:
        v = float(str(num).replace(",", ""))
    except (TypeError, ValueError):
        return None
    s = (suffix or "").lower()
    if s == "k" or s == "grand":
        v *= 1_000
    elif s == "m":
        v *= 1_000_000
    return int(v)


def parse_budget(text: str) -> Optional[BudgetParse]:
    """Parse ONE budget expression from free text. Ordered most-specific-first; every branch applies the
    spec-unit guard so "under 2 kg" / "16 gb" never becomes money. Returns None when nothing matches."""
    q = str(text or "").lower()
    if not q:
        return None

    # DELTA phrasings ("widen by 200", "increase the budget by 300") are relative adjustments owned by
    # the caller's delta machinery — a grammar that returned "$300 ceiling" here would stomp the envelope.
    if re.search(r"\b(?:widen|increase|raise|bump|extend|add|decrease|reduce|narrow)\b[^.]{0,24}\bby\s*[\$€£]?\s*\d", q):
        return None

    # 1) explicit range — "$500-$1000", "between 1200 and 1500", cue-anchored bare "budget 1200 to 1500"
    m = (re.search(rf"{_CUR}\s*{_NUM}\s*(?:-|–|—|to|and)\s*{_CUR}?\s*{_NUM}{_UNIT_GUARD}", q)
         or re.search(rf"\b(?:between|from)\s*{_CUR}?\s*{_NUM}\s*(?:-|–|—|to|and)\s*{_CUR}?\s*{_NUM}{_UNIT_GUARD}", q)
         or re.search(rf"\b(?:budget|price(?:\s+range)?|spend)\s*(?:is|of|:|=|for)?\s*{_CUR}?\s*{_NUM}\s*(?:-|–|—|to|and)\s*{_CUR}?\s*{_NUM}{_UNIT_GUARD}", q))
    if m:
        a, b = _to_int(m.group(1), m.group(2)), _to_int(m.group(3), m.group(4))
        if a is not None and b is not None and a != b:
            return BudgetParse(min(a, b), max(a, b), "range")

    # 2) revision DOWN — "cut it to 1000 max", "drop the budget to 800": a new CEILING (floor cleared).
    #    Requires a budget cue and >= 100 so "reduce to 10" stays a quantity amendment.
    m = re.search(rf"\b(?:cut|drop|lower|bring|reduce)\s+(?:it|that|this|the\s+(?:budget|price|spend))?\s*"
                  rf"(?:down\s+)?to\s*{_CUR}?\s*{_NUM}\b", q)
    if m and re.search(rf"\bmax\b|\bbudget\b|\bspend\b|\bprice\b|{_CUR}|\bgrand\b|\bk\b", q):
        v = _to_int(m.group(1), m.group(2))
        if v is not None and v >= 100:
            return BudgetParse(None, v, "revision_down")

    # 3) per-unit ceiling — "1900 each", "$1,800 per <anything>" (vertical-blind: "per X" is a per-unit
    #    budget cue regardless of what X is — the noun is never inspected)
    m = re.search(rf"{_CUR}?\s*{_NUM}\s*(?:each\b|a\s?piece\b|apiece\b|per\s+[a-z]+)", q)
    if m:
        v = _to_int(m.group(1), m.group(2))
        if v is not None and v >= 50:
            return BudgetParse(None, v, "per_unit")

    # 4) ceiling — "under 1500", "below $2k", "up to 5 grand", "no more than 1200", "1500 max"
    m = (re.search(rf"\b(?:under|below|less than|within|up\s*to|no more than|max(?:imum)?(?:\s+of)?)\s*{_CUR}?\s*{_NUM}{_UNIT_GUARD}", q)
         or re.search(rf"{_CUR}?\s*{_NUM}\s+max\b", q))
    if m:
        v = _to_int(m.group(1), m.group(2))
        if v is not None and v >= 50:
            return BudgetParse(None, v, "ceiling")

    # 5) floor — "over 1000", "at least $800", "minimum 500"
    m = re.search(rf"\b(?:over|above|at least|more than|minimum(?:\s+of)?|starting\s+at)\s*{_CUR}?\s*{_NUM}{_UNIT_GUARD}", q)
    if m:
        v = _to_int(m.group(1), m.group(2))
        if v is not None and v >= 50:
            return BudgetParse(v, None, "floor")

    # 6) budget-anchored single value BEFORE the around-band — "can spend about $2000" is a stated
    #    CEILING (the buyer named their limit), not a fuzzy band. "budget is 1600", "budget: $1,400".
    m = re.search(rf"\b(?:budget|spend|afford\w*)\b[^\d$€£]{{0,18}}{_CUR}?\s*{_NUM}{_UNIT_GUARD}(?!\s*(?:-|–|—|to|and)\s*[\$€£]?\d)", q)
    if m:
        v = _to_int(m.group(1), m.group(2))
        if v is not None and v >= 50:
            return BudgetParse(None, v, "ceiling")

    # 7) around — "around 1500", "about $2k", "roughly 1200" → ±20% band
    m = re.search(rf"\b(?:around|about|roughly|approx\w*|~)\s*{_CUR}?\s*{_NUM}{_UNIT_GUARD}", q)
    if m:
        v = _to_int(m.group(1), m.group(2))
        if v is not None and v >= 50:
            return BudgetParse(int(v * 0.8), int(v * 1.2), "around")

    return None
