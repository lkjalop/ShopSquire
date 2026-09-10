"""Budget grammar (agnostic CORE) — the ONE place a money budget is parsed from buyer text.

Near-duplicate budget grammars grew across the stack and produced contradictory
answers. This module is the canonical buyer-query grammar. Callers consume its
typed result; response-price prose remains a separate parsing responsibility.

Vertical-blind: pure numbers, currency symbols, and generic verbs — no product vocabulary. Pure function,
no DB, no network. Returns a BudgetParse or None (None = this grammar saw no budget; the caller may still
try its legacy patterns).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

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
# Currency markers accepted before a money amount. ISO codes are bounded to the
# currencies supported by the commerce adapters; accepting any three letters
# would turn model/spec identifiers into money.
_CUR = r"(?:[\$€£]|(?:aud|usd|cad|nzd|sgd|hkd|gbp|eur|jpy)\b)"


@dataclass(frozen=True)
class BudgetParse:
    budget_min: Optional[int]
    budget_max: Optional[int]
    mode: str               # range | ceiling | floor | around | revision_down | per_unit
    source_span: Optional[Tuple[int, int]] = None

    @property
    def found(self) -> bool:
        return self.budget_min is not None or self.budget_max is not None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "budget_min": self.budget_min,
            "budget_max": self.budget_max,
            "mode": self.mode,
            "source_span": list(self.source_span) if self.source_span is not None else None,
        }

    @classmethod
    def from_dict(cls, value: Dict[str, Any] | None) -> Optional["BudgetParse"]:
        if not isinstance(value, dict):
            return None
        span = value.get("source_span")
        bounded_span = None
        if isinstance(span, (list, tuple)) and len(span) == 2:
            try:
                bounded_span = (max(0, int(span[0])), max(0, int(span[1])))
            except (TypeError, ValueError):
                bounded_span = None
        try:
            lo = int(value["budget_min"]) if value.get("budget_min") is not None else None
            hi = int(value["budget_max"]) if value.get("budget_max") is not None else None
        except (TypeError, ValueError):
            return None
        mode = str(value.get("mode") or "").strip()
        if mode not in {"range", "ceiling", "floor", "around", "revision_down", "per_unit"}:
            return None
        parsed = cls(lo, hi, mode, bounded_span)
        return parsed if parsed.found else None


def canonical_budget_from_accepted_slots(
    current: Dict[str, Any] | None,
    accepted_slots: Dict[str, Any] | None,
) -> Dict[str, Any] | None:
    """Preserve a previously accepted case budget without reparsing text.

    The current turn's ``BudgetParse`` remains authoritative when present.
    Replacement/refinement turns may carry a durable, structured budget in
    confirmed slots; projecting it here keeps the new revision truthful while
    leaving ingress fact extraction literal to the current buyer message.
    """

    parsed = BudgetParse.from_dict(current)
    slots = accepted_slots if isinstance(accepted_slots, dict) else {}
    if parsed is not None:
        # An amount-only transport projection has no buyer-authored span. It
        # cannot silently relabel an unchanged accepted approximation.
        if (parsed.source_span is None and slots.get("budget_mode") == "around"
                and parsed.budget_min is None and slots.get("budget_min") is None
                and parsed.budget_max == slots.get("budget_max")):
            return BudgetParse(None, parsed.budget_max, "around", None).to_dict()
        return parsed.to_dict()

    def amount(key: str) -> Optional[int]:
        value = slots.get(key)
        if isinstance(value, bool) or value is None:
            return None
        try:
            bounded = int(float(value))
        except (TypeError, ValueError):
            return None
        return bounded if bounded > 0 else None

    lo = amount("budget_min")
    hi = amount("budget_max")
    if lo is None and hi is None:
        total_cents = amount("total_budget_cents")
        hi = total_cents // 100 if total_cents is not None else None
    if lo is None and hi is None:
        return None
    mode = "range" if lo is not None and hi is not None else "floor" if lo is not None else "ceiling"
    if slots.get("budget_mode") == "around" and lo is None and hi is not None:
        mode = "around"
    return BudgetParse(lo, hi, mode, None).to_dict()


@dataclass(frozen=True)
class PriceIntent:
    """Buyer-facing meaning of a parsed price, separate from authorization."""

    mode: str  # hard_ceiling | target_band | affordability_check | range | floor
    target: Optional[int]
    preferred_min: Optional[int]
    preferred_max: Optional[int]
    hard_ceiling: Optional[int]


def interpret_price_intent(text: str) -> Optional[PriceIntent]:
    """Project canonical budget grammar into deterministic display semantics.

    The parsed budget remains the authority boundary. This projection only tells
    the buyer-facing shelf whether a number is a limit, target, or question.
    """
    parsed = parse_budget(text)
    if parsed is None:
        return None
    q = str(text or "").lower()
    affordability = bool(
        re.search(r"\b(?:is|would|will|could)\s*(?:[\$€£]|(?:aud|usd|cad|nzd|sgd|hkd|gbp|eur|jpy)\b)?\s*[\d,]+(?:\.\d+)?\s+(?:be\s+)?(?:enough|sufficient|insufficient|ok|okay|acceptable|excessive|overkill|too\s+much)\b", q)
        or re.search(r"\benough\b[^\d$€£]{0,18}(?:at|with|on)\s*(?:[\$€£]|(?:aud|usd|cad|nzd|sgd|hkd|gbp|eur|jpy)\b)?\s*[\d,]+", q)
    )
    if affordability and parsed.budget_max is not None:
        target = parsed.budget_max
        return PriceIntent("affordability_check", target, int(target * 0.75), target, target)
    if parsed.mode == "around":
        low, high = parsed.budget_min, parsed.budget_max
        target = int((low + high) / 2) if low is not None and high is not None else high or low
        return PriceIntent("target_band", target, low, high, high)
    if parsed.mode in {"ceiling", "revision_down", "per_unit"}:
        return PriceIntent("hard_ceiling", parsed.budget_max, None, parsed.budget_max, parsed.budget_max)
    if parsed.mode == "range" and parsed.budget_min is not None and parsed.budget_max is not None:
        target = int((parsed.budget_min + parsed.budget_max) / 2)
        return PriceIntent("range", target, parsed.budget_min, parsed.budget_max, parsed.budget_max)
    return PriceIntent("floor", parsed.budget_min, parsed.budget_min, None, None)


def parse_budget_delta(text: str) -> Optional[int]:
    """Return a signed, buyer-stated relative budget change in whole currency units.

    Relative changes are intentionally separate from :func:`parse_budget`: treating
    ``widen the budget by 600`` as a new 600-unit ceiling would erase the accepted
    session constraint. The caller must have an authoritative prior budget before
    applying this value.
    """
    q = str(text or "").lower()
    if not q or not re.search(r"\b(?:budget|price\s+range)\b", q):
        return None
    up = bool(re.search(r"\b(?:widen|increase|raise|bump|expand|broaden|extend|loosen)\b", q))
    down = bool(re.search(r"\b(?:reduce|decrease|lower|tighten|cut|shrink|narrow)\b", q))
    if up == down:
        return None
    match = re.search(
        rf"\bby\s*{_CUR}?\s*{_NUM}(?:\s*(?:-|to)\s*{_CUR}?\s*{_NUM})?",
        q,
    )
    if not match:
        return None
    first = _to_int(match.group(1), match.group(2))
    second = (
        _to_int(match.group(3), match.group(4))
        if match.lastindex and match.lastindex >= 4 and match.group(3)
        else None
    )
    magnitude = max(value for value in (first, second) if value is not None)
    if magnitude <= 0:
        return None
    return magnitude if up else -magnitude


def classify_budget_scope(text: str) -> str:
    """Classify an explicitly stated budget as ``per_unit``, ``total`` or ``unknown``.

    This is deliberately separate from amount parsing: callers may receive the amount as a
    structured field while scope still lives in the buyer's words.  Per-unit language wins when
    both families appear because it is the more precise authorization.
    """
    q = str(text or "").lower()
    if re.search(r"\b(?:each|apiece|a\s+piece|per\s+(?:unit|item|device|laptop|computer|pc))\b", q):
        return "per_unit"
    if re.search(
        r"\b(?:total(?:\s+(?:order|annual|yearly|monthly))?\s+budget|budget\s+(?:for|across)\s+(?:all|the\s+whole)|"
        r"(?:keep|cap|hold)\s+(?:the\s+)?total(?:\s+(?:under|below|at|to))?|"
        r"all\s+in|altogether|combined|grand\s+total|in\s+total|for\s+all)\b",
        q,
    ):
        return "total"
    if re.search(
        r"\b(?:(?:aud|usd|cad|nzd|gbp|eur)\s*)?\$?\s*[\d,]+(?:\.\d+)?\s+total\b",
        q,
    ):
        return "total"
    return "unknown"


def resolve_total_budget_cap(
    text: str,
    *,
    normalized_budget_max: Optional[float],
    prior_total_budget_cents: Optional[int] = None,
    prior_budget_scope: Optional[str] = None,
) -> Optional[float]:
    """Resolve a whole-order ceiling without reinterpreting a normalized per-unit cap."""
    if classify_budget_scope(text) != "total":
        return None
    parsed = parse_budget(text)
    if parsed is not None and parsed.budget_max is not None:
        return float(parsed.budget_max)
    if prior_budget_scope == "total" and prior_total_budget_cents is not None:
        try:
            prior = int(prior_total_budget_cents)
        except (TypeError, ValueError):
            prior = 0
        if prior > 0:
            return prior / 100.0
    try:
        fallback = float(normalized_budget_max) if normalized_budget_max is not None else None
    except (TypeError, ValueError):
        return None
    return fallback if fallback is not None and fallback > 0 else None


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


def _min_plausible_budget() -> int:
    """The smallest number treated as money rather than a spec ("15 inch"). 50 fit high-ticket
    verticals but starved low-ticket ones (pharmacy "under 25" never parsed) — so the floor is a
    profile slot, ``budget_floor``, defaulting to 50. Threshold DATA lives in the StoreProfile;
    the guard MECHANISM stays here."""
    try:
        from src.app.platform.store_profile import profile_slot
        v = int(profile_slot("budget_floor", default=50) or 50)
        return v if v > 0 else 50
    except Exception:
        return 50


def parse_budget(text: str) -> Optional[BudgetParse]:
    """Parse ONE budget expression from free text. Ordered most-specific-first; every branch applies the
    spec-unit guard so "under 2 kg" / "16 gb" never becomes money. Returns None when nothing matches."""
    _floor = _min_plausible_budget()
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
            return BudgetParse(min(a, b), max(a, b), "range", m.span())
    m = re.search(
        rf"\b(?:good|options?|products?|recommendations?)\b[^.?!]{{0,16}}"
        rf"\bfor\s*{_CUR}?\s*{_NUM}\s*(?:-|to|and)\s*"
        rf"{_CUR}?\s*{_NUM}{_UNIT_GUARD}",
        q,
    )
    if m:
        a, b = _to_int(m.group(1), m.group(2)), _to_int(m.group(3), m.group(4))
        if a is not None and b is not None and a != b:
            return BudgetParse(min(a, b), max(a, b), "range", m.span())

    # 2) revision DOWN — "cut it to 1000 max", "drop the budget to 800": a new CEILING (floor cleared).
    #    Requires a budget cue and >= 100 so "reduce to 10" stays a quantity amendment.
    m = re.search(rf"\b(?:cut|drop|lower|bring|reduce)\s+(?:it|that|this|the\s+(?:budget|price|spend))?\s*"
                  rf"(?:down\s+)?to\s*{_CUR}?\s*{_NUM}\b", q)
    if m and re.search(rf"\bmax\b|\bbudget\b|\bspend\b|\bprice\b|{_CUR}|\bgrand\b|\bk\b", q):
        v = _to_int(m.group(1), m.group(2))
        if v is not None and v >= 100:
            return BudgetParse(None, v, "revision_down", m.span())

    # 3) per-unit ceiling — "1900 each", "$1,800 per <anything>" (vertical-blind: "per X" is a per-unit
    #    budget cue regardless of what X is — the noun is never inspected)
    m = re.search(rf"{_CUR}?\s*{_NUM}\s*(?:each\b|a\s?piece\b|apiece\b|per\s+[a-z]+)", q)
    if m:
        v = _to_int(m.group(1), m.group(2))
        if v is not None and v >= _floor:
            return BudgetParse(None, v, "per_unit", m.span())

    # 3b) explicit whole-order amount with trailing scope: "$3500 total". Currency is
    # mandatory here so a specification followed by the word "total" cannot become money.
    m = re.search(rf"{_CUR}\s*{_NUM}\s+(?:in\s+)?total\b", q)
    if m:
        v = _to_int(m.group(1), m.group(2))
        if v is not None and v >= _floor:
            return BudgetParse(None, v, "ceiling", m.span())

    # 4) ceiling — "under 1500", "below $2k", "up to 5 grand", "no more than 1200", "1500 max"
    m = (re.search(rf"\b(?:under|below|less than|within|up\s*to|no more than|max(?:imum)?(?:\s+of)?)\s*{_CUR}?\s*{_NUM}{_UNIT_GUARD}", q)
         or re.search(rf"{_CUR}?\s*{_NUM}\s+max\b", q))
    if m:
        v = _to_int(m.group(1), m.group(2))
        if v is not None and v >= _floor:
            return BudgetParse(None, v, "ceiling", m.span())

    # 4b) NEGATED floor = ceiling — "nothing over 2k", "not above 1500", "don't go over 1800",
    #     "never more than 900". Without this, the floor rule below read these as MINIMUMS and
    #     inverted the buyer's budget (2026-07-07 audit: "nothing over 2k" -> budget_min=2000).
    m = re.search(rf"\b(?:nothing|not|no|don'?t|won'?t|never|without\s+going)\s+"
                  rf"(?:go(?:ing)?\s+|to\s+go\s+|want(?:\s+to)?\s+go\s+)?"
                  rf"(?:over|above|past|beyond|more\s+than|exceeding)\s*{_CUR}?\s*{_NUM}{_UNIT_GUARD}", q)
    if m:
        v = _to_int(m.group(1), m.group(2))
        if v is not None and v >= _floor:
            return BudgetParse(None, v, "ceiling", m.span())

    # 5) floor — "over 1000", "at least $800", "minimum 500"
    m = re.search(rf"\b(?:over|above|at least|more than|minimum(?:\s+of)?|starting\s+at)\s*{_CUR}?\s*{_NUM}{_UNIT_GUARD}", q)
    if m:
        v = _to_int(m.group(1), m.group(2))
        if v is not None and v >= _floor:
            return BudgetParse(v, None, "floor", m.span())

    # Explicit approximation language must win over the broad budget/spend
    # anchor below. Preserve the literal target; approximation does not grant
    # a percentage uplift. Above-target exploration needs separate permission.
    m = re.search(rf"\b(?:around|about|roughly|approx\w*|~)\s*{_CUR}?\s*{_NUM}{_UNIT_GUARD}", q)
    if m:
        v = _to_int(m.group(1), m.group(2))
        if v is not None and v >= _floor:
            return BudgetParse(None, v, "around", m.span())

    # 6) Non-approximate budget/spend anchors: "budget is 1600", "budget: $1,400".
    m = re.search(rf"\b(?:budget|spend|afford\w*)\b[^\d$€£]{{0,18}}{_CUR}?\s*{_NUM}{_UNIT_GUARD}(?!\s*(?:-|–|—|to|and)\s*[\$€£]?\d)", q)
    if m:
        v = _to_int(m.group(1), m.group(2))
        if v is not None and v >= _floor:
            return BudgetParse(None, v, "ceiling", m.span())

    # 7) Affordability and remaining literal target forms.
    # Affordability question: "is $1800 enough?", "is AUD 3000 excessive
    # for X?", or "do I have enough at $1000?". This is a proposed maximum,
    # not a product specification. The adjective is buyer-facing semantics;
    # it must not cause the amount to disappear before workload resolution.
    m = (re.search(rf"\b(?:is|would|will|could)\s*{_CUR}?\s*{_NUM}\s+(?:be\s+)?(?:enough|sufficient|insufficient)\b", q)
         or re.search(rf"\b(?:is|would)\s*{_CUR}?\s*{_NUM}\s+(?:be\s+)?(?:ok|okay|acceptable|excessive|overkill|too\s+much)\b{_UNIT_GUARD}", q)
         or re.search(rf"\benough\b[^\d$â‚¬Â£]{{0,18}}(?:at|with|on)\s*{_CUR}?\s*{_NUM}{_UNIT_GUARD}", q))
    if m:
        v = _to_int(m.group(1), m.group(2))
        if v is not None and v >= _floor:
            return BudgetParse(None, v, "ceiling", m.span())

    m = re.search(rf"\b(?:around|about|roughly|approx\w*|~)\s*{_CUR}?\s*{_NUM}{_UNIT_GUARD}", q)
    if m:
        v = _to_int(m.group(1), m.group(2))
        if v is not None and v >= _floor:
            return BudgetParse(None, v, "around", m.span())

    # A singular product price ("I need a 4000 laptop") is a target tier,
    # not permission to ignore the amount and start at the cheapest item. The
    # singular article separates it from quantities such as "need 100 laptops".
    m = re.search(
        rf"\b(?:need|want|looking\s+for|on|for)\s+(?:a|an|one)\s+"
        rf"{_CUR}?\s*{_NUM}{_UNIT_GUARD}\s+[a-z]",
        q,
    )
    if m:
        v = _to_int(m.group(1), m.group(2))
        if v is not None and v >= _floor:
            return BudgetParse(None, v, "around", m.span())

    # 8) bare currency-anchored amount — "headsets for $1200", "$1,200 for those". The currency
    #    marker is ITSELF the money cue, so no cue word is required here; a bare number with NO
    #    currency marker still never parses (that stays a quantity/spec). This is the LAST branch
    #    so every cue-anchored reading above wins first, and the plausibility floor still applies
    #    (so "$45 per user per month" stays commercial terms, not a hardware ceiling).
    m = re.search(rf"{_CUR}\s*{_NUM}{_UNIT_GUARD}", q)
    if m:
        v = _to_int(m.group(1), m.group(2))
        if v is not None and v >= _floor:
            return BudgetParse(None, v, "ceiling", m.span())

    return None
