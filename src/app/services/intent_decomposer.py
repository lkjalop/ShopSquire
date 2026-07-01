"""Multi-intent turn decomposition (agnostic CORE) — the "not-dumb" parser.

A real buyer turn often carries SEVERAL intents at once: amend the quantity of an already-chosen item, add
new product lines, scope a budget to just those lines, and voice an objection — e.g.

    "nah that's too expensive, actually I need 15 instead? what options for headsets and hard drives.
     I have a budget for 1200 for those?"

A single-intent parser loses the laptop, applies one global budget, or turns "15" into a new line. This
module decomposes ONE turn into a structured, validated plan:

    { amendments:[{ref,new_qty}], new_lines:[{category,qty}], budget_scopes:[{applies_to,min,max}],
      global_budget, objection, confidence, notes }

Design — "AI proposes, deterministic authorizes" applied to PARSING: deterministic primitives + explicit
BINDING RULES are the default and the safety net (an optional schema-constrained LLM can refine ambiguous
bindings later; it never sets a quantity or budget without passing these rules). Vertical-blind: categories
and refs are OPAQUE tokens; only numbers, currency, and grammar cues are read — no product vocabulary.
Pure: no DB, no LLM, no request locals. The caller resolves ``__last__`` / ``__new__`` against session state.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

# ── grammar cues (commerce-generic, NOT product vocabulary) ──────────────────
_AMEND_RE = re.compile(
    r"\b(?:instead|actually|make\s+it|change\s+(?:it|that|to)|rather|nah|scratch\s+that|"
    r"on\s+second\s+thought|let'?s?\s+(?:do|say)|i(?:'|\s+a)?m?\s+need|i\s+need|i\s+want)\b",
    re.IGNORECASE)
_REQUEST_RE = re.compile(
    r"\b(?:options?\s+for|what\s+(?:about\s+)?|recommend|suggest|looking\s+for|show\s+me|"
    r"add|any\s+(?:good\s+)?|some|need|want|get\s+me|find\s+me)\b", re.IGNORECASE)
# a budget SCOPE cue ("$1200 for those") means the budget binds to the just-named new lines, not globally.
_SCOPE_RE = re.compile(r"\bfor\s+(?:those|them|these|the\s+(?:accessories|extras|rest)|both|all)\b", re.IGNORECASE)
_PRICE_OBJECTION_RE = re.compile(
    r"\b(?:too\s+(?:expensive|much|pricey|dear|costly)|expensive|can'?t\s+afford|over\s+budget|"
    r"out\s+of\s+(?:my\s+)?budget|cheaper|pricey)\b", re.IGNORECASE)

# nouns that are NEVER a product category (referents, units, filler) — excluded from category extraction.
_STOP_NOUNS = {
    "those", "these", "them", "ones", "others", "options", "units", "items", "pieces", "pcs", "things",
    "products", "models", "dollars", "bucks", "budgets", "prices", "specs", "reviews", "days", "weeks",
    "months", "years", "hours", "sales", "deals", "extras", "accessories", "rest", "results", "matches",
    "picks", "recommendations", "yours", "ours", "goods",
}
_NUM = r"(\d[\d,]{0,6})"


@dataclass(frozen=True)
class Amendment:
    ref: str          # "__last__" (the last chosen/shortlisted item) — resolved by the caller
    new_qty: int


@dataclass(frozen=True)
class NewLine:
    category: str     # opaque product-category token (e.g. "headsets"); qty unset = "show options"
    qty: Optional[int] = None


@dataclass(frozen=True)
class BudgetScope:
    applies_to: Tuple[str, ...]        # ("__new__",) or the category tokens the budget scopes to
    budget_min: Optional[int] = None
    budget_max: Optional[int] = None


@dataclass(frozen=True)
class TurnIntents:
    amendments: List[Amendment] = field(default_factory=list)
    new_lines: List[NewLine] = field(default_factory=list)
    budget_scopes: List[BudgetScope] = field(default_factory=list)
    global_budget: Optional[Tuple[Optional[int], Optional[int]]] = None   # (min,max) when NOT scoped
    objection: Optional[str] = None                                        # "price" | None
    confidence: float = 1.0
    notes: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "amendments": [{"ref": a.ref, "new_qty": a.new_qty} for a in self.amendments],
            "new_lines": [{"category": n.category, "qty": n.qty} for n in self.new_lines],
            "budget_scopes": [{"applies_to": list(b.applies_to), "budget_min": b.budget_min,
                               "budget_max": b.budget_max} for b in self.budget_scopes],
            "global_budget": list(self.global_budget) if self.global_budget else None,
            "objection": self.objection, "confidence": round(self.confidence, 3), "notes": list(self.notes),
        }


def decompose_turn(query: str, *, has_prior_selection: bool = False) -> TurnIntents:
    """Decompose one buyer turn into its intents. ``has_prior_selection`` = there is a chosen/shortlisted item
    to amend (from session state); without it, a bare "15 instead" is ambiguous and is surfaced as a note
    instead of a silent amendment (never guess on quantity)."""
    q = str(query or "")
    ql = q.lower()
    notes: List[str] = []

    objection = "price" if _PRICE_OBJECTION_RE.search(ql) else None

    # ── budgets: value(s) + whether a SCOPE cue binds them to the new lines ──────────────────────────
    b_min, b_max, budget_span = _extract_budget(ql)
    scoped = bool(budget_span and _has_scope_cue_near(ql, budget_span))

    # ── new lines: category list after a request cue (numbers → order lines; bare plurals → "options") ──
    new_lines = _extract_new_lines(ql)

    # ── amendment: an amendment cue + a BARE number that is NOT a new-line qty and NOT the budget ──────
    amendments: List[Amendment] = []
    for m in re.finditer(r"\b" + _NUM + r"\b", ql):
        n = _to_int(m.group(1))
        if n is None or not (1 <= n <= 500):
            continue
        if budget_span and budget_span[0] <= m.start() < budget_span[1]:
            continue  # this number IS the budget, not a quantity
        before = ql[max(0, m.start() - 30):m.start()]
        after = ql[m.end():m.end() + 18]
        # a quantity amendment: an amend cue precedes it AND it isn't immediately followed by a category noun
        if _AMEND_RE.search(before) and not re.match(r"\s+[a-z][a-z/\-]{2,}s\b", after):
            if has_prior_selection:
                amendments.append(Amendment(ref="__last__", new_qty=n))
            else:
                notes.append(f"amend-to-{n} ignored: no prior selection to amend (ask which item).")
            break  # one amendment per turn (the buyer changes their mind once)

    # ── bind budgets ────────────────────────────────────────────────────────────────────────────────
    budget_scopes: List[BudgetScope] = []
    global_budget: Optional[Tuple[Optional[int], Optional[int]]] = None
    if b_min is not None or b_max is not None:
        if scoped and new_lines:
            budget_scopes.append(BudgetScope(applies_to=("__new__",), budget_min=b_min, budget_max=b_max))
        elif scoped and not new_lines:
            notes.append("scoped budget ('for those') but no new lines to bind it to — kept global.")
            global_budget = (b_min, b_max)
        else:
            global_budget = (b_min, b_max)

    # ── confidence: lower it when the turn is genuinely mixed/ambiguous so the caller can confirm ──────
    intents_present = sum(bool(x) for x in (amendments, new_lines, budget_scopes or global_budget, objection))
    confidence = 1.0
    if amendments and not has_prior_selection:
        confidence = min(confidence, 0.5)
    if scoped and not new_lines:
        confidence = min(confidence, 0.6)
    if intents_present >= 3:
        confidence = min(confidence, 0.75)   # a rich multi-intent turn → worth a confirmation card
        notes.append("multi-intent turn — confirm before applying (amend + new lines + budget).")

    return TurnIntents(amendments=amendments, new_lines=new_lines, budget_scopes=budget_scopes,
                       global_budget=global_budget, objection=objection, confidence=confidence, notes=notes)


# ── primitives ────────────────────────────────────────────────────────────────
def _extract_budget(ql: str) -> Tuple[Optional[int], Optional[int], Optional[Tuple[int, int]]]:
    """(min, max, span) — a range, a ceiling ('under/for 1200'), or a bare '$1200'. span is the char range of
    the matched budget so callers can exclude those digits from quantity parsing."""
    rng = re.search(r"[\$€£]?\s*" + _NUM + r"\s*(?:to|-|–|and)\s*[\$€£]?\s*" + _NUM + r"\b", ql)
    if rng:
        lo, hi = _to_int(rng.group(1)), _to_int(rng.group(2))
        if lo is not None and hi is not None and lo < hi:
            return lo, hi, rng.span()
    m = re.search(r"\b(?:budget(?:\s+(?:of|is|for))?|under|below|up\s*to|for|around|about|max(?:imum)?)\s*"
                  r"[\$€£]?\s*" + _NUM + r"\b", ql) or re.search(r"[\$€£]\s*" + _NUM + r"\b", ql)
    if m:
        v = _to_int(m.group(1))
        if v is not None and v >= 50:   # 50+ is a price, not a quantity
            return None, v, m.span()
    return None, None, None


def _has_scope_cue_near(ql: str, budget_span: Tuple[int, int]) -> bool:
    """A scope cue ('for those') within a short window AFTER the budget binds it to the new lines."""
    tail = ql[budget_span[1]:budget_span[1] + 40]
    return bool(_SCOPE_RE.search(tail)) or bool(_SCOPE_RE.search(ql[max(0, budget_span[0] - 25):budget_span[0]]))


def _extract_new_lines(ql: str) -> List[NewLine]:
    """Category lines requested in the turn. A 'N <noun>' is a quantified line; a bare plural noun list after
    a request cue ('options for headsets and hard drives') is an 'options' line (qty unset). Stop nouns and
    referents are excluded. De-duplicated, order-preserved."""
    out: List[NewLine] = []
    seen: set = set()

    def _add(cat: str, qty: Optional[int]) -> None:
        c = cat.strip()
        if not c or c in seen or c.rstrip("s") in _STOP_NOUNS or c in _STOP_NOUNS:
            return
        seen.add(c)
        out.append(NewLine(category=c, qty=qty))

    # quantified lines first: "N <adj>? <plural noun>"
    for m in re.finditer(r"\b(\d{1,4})\s+(?:[a-z][a-z/\-]{2,}\s+){0,2}([a-z][a-z/\-]{2,}s)\b", ql):
        n = _to_int(m.group(1))
        noun = m.group(2)
        if n is not None and 1 < n <= 500:
            # capture an optional preceding adjective as part of the category ("wireless headsets")
            _add(_two_word_category(ql, m.start(2), noun), n)
    # bare category lists after a request cue: "options for headsets and hard drives"
    for rm in _REQUEST_RE.finditer(ql):
        seg = ql[rm.end():rm.end() + 80]
        # stop the segment at a budget/clause boundary
        seg = re.split(r"[.?!]|\bfor\s+\$?\s*\d|\bbudget\b|\bunder\b|\bwithin\b", seg, 1)[0]
        for term in re.split(r"\s*(?:,|\+|;|\band\b|\bor\b)\s*", seg):
            tm = re.search(r"(?:([a-z][a-z/\-]{2,})\s+)?([a-z][a-z/\-]{2,}s)\b", term.strip())
            if tm:
                _add(_join_adj(tm.group(1), tm.group(2)), None)
    return out


def _two_word_category(ql: str, noun_start: int, noun: str) -> str:
    adj = re.search(r"([a-z][a-z/\-]{2,})\s+$", ql[max(0, noun_start - 20):noun_start])
    return _join_adj(adj.group(1) if adj else None, noun)


def _join_adj(adj: Optional[str], noun: str) -> str:
    adj = (adj or "").strip()
    if adj and adj not in _STOP_NOUNS and not adj.isdigit() and adj not in (
            "of", "the", "a", "an", "some", "any", "good", "for", "with", "and", "or"):
        return f"{adj} {noun}"
    return noun


def _to_int(v: Any) -> Optional[int]:
    try:
        return int(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return None
