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

import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

# injected LLM: takes a prompt, returns raw JSON text. The CORE never imports a model — the live adapter
# supplies the real (schema-forced) call; tests supply a stub. Keeps this module pure + vertical-blind.
LLMFn = Callable[[str], str]

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

# change/add signals that the deterministic parser doesn't fully cover — their presence WITHOUT a captured
# amendment/new-line is what triggers the LLM binding fallback (the "trap" cases like "reduce to 10 and get
# 40 mice" or "make it 15 and add a docking station" that the regex verb set misses).
_CHANGE_VERB_RE = re.compile(
    r"\b(?:reduce|lower|drop|cut|bump|bring|only|down\s+to|make\s+it|change|instead|halve|double|"
    r"remove|get\s+rid|delete|take\s+out|ditch|scrap)\b", re.I)

# REMOVAL of a named cart line ("get rid of the Alpha X1 and the Beta Pro", "remove the monitor"). The verb
# starts the capture; the object runs to the next boundary (punctuation / a change-verb starting the next
# clause). "get rid off" (common typo) is covered by of+.
_REMOVE_VERB_RE = re.compile(
    r"\b(?:remove|get\s+rid\s+of+|delete|take\s+out|take\s+off|ditch|scrap|do\s+away\s+with)\b", re.I)
_REMOVE_STOP_RE = re.compile(
    r"[,;?!]|\b(?:reduce|change|set|make|lower|bump|cut|increase|update|add|get\s+me|then|instead|please)\b", re.I)
# NAMED quantity amendment ("reduce the Alpha Slim 3 to 20") - binds the qty to a PRODUCT-NAME
# reference instead of the positional __last__.
_NAMED_QTY_RE = re.compile(
    r"\b(?:reduce|change|set|make|lower|bump|cut|increase|update|bring)\s+(?:the\s+|that\s+|my\s+)?"
    r"(?P<obj>[^,;?!]{3,70}?)\s+(?:down\s+|up\s+)?to\s+(?P<n>\d[\d,]{0,6})\b", re.I)
# referents that are NOT a product-name reference (those fall back to the positional __last__ path)
_REF_PRONOUNS = {"it", "that", "this", "them", "those", "these", "the order", "order", "quantity", "qty",
                 "the quantity", "the qty", "everything", "all", "budget", "the budget"}


def _clean_ref(text: str) -> str:
    """A free-text product-name reference, trimmed of leading articles/fillers. Opaque - no vocabulary."""
    t = re.sub(r"^(?:the|that|this|those|these|my|our|a|an)\s+", "", str(text or "").strip(), flags=re.I)
    return t.strip(" \t-")[:80]
_ADD_VERB_RE = re.compile(
    r"\b(?:add|get|grab|throw\s+in|include|also|plus|as\s+well|toss\s+in|chuck\s+in)\b", re.I)


@dataclass(frozen=True)
class Amendment:
    ref: str          # "__last__" (positional) OR a free-text product-name reference - resolved by the caller
    new_qty: int      # 0 = REMOVE the referenced line (executed as qty-0 by the human-confirmed card)


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


def decompose_turn(query: str, *, has_prior_selection: bool = False,
                   llm_fn: Optional["LLMFn"] = None,
                   prior_context: Optional[Dict[str, Any]] = None) -> TurnIntents:
    """Decompose one buyer turn into its intents. Hybrid ("AI proposes, deterministic authorizes"):

    1. the DETERMINISTIC parser runs first (fast, free, covers the common phrasings);
    2. if it likely MISSED an intent — a change/add signal is present but the corresponding amendment/new-line
       wasn't captured, or confidence is low — and an ``llm_fn`` is injected, a schema-constrained LLM re-parses
       the turn; its output is VALIDATED by the same grammar rules (qty 1..500, budget >= 50, ref __last__)
       before it's trusted, so the LLM never sets a quantity or budget the deterministic authorizer rejects.

    The downstream scatter-gather guard + confirmation card are the final safety net, so even a bad LLM parse
    can never silently apply a wrong plan. ``llm_fn(prompt) -> str`` returns raw JSON text (injected; the live
    adapter supplies the real model, tests a stub). Pure otherwise — no DB, no network here."""
    deterministic = _decompose_deterministic(str(query or ""), has_prior_selection)
    if llm_fn is None or not _needs_llm_binding(deterministic, str(query or "").lower(), has_prior_selection):
        return deterministic
    refined = _bind_with_llm(str(query or ""), has_prior_selection, llm_fn, prior_context=prior_context)
    return refined if refined is not None else deterministic


def _decompose_deterministic(query: str, has_prior_selection: bool) -> TurnIntents:
    """The deterministic primitive parser (grammar cues + binding rules). Vertical-blind, pure."""
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
    consumed: List[Tuple[int, int]] = []   # spans claimed by removals/named refs; bare numbers inside are NOT quantities

    # (a) REMOVALS: "get rid of the Alpha X1 and the Beta Pro" -> one qty-0 amendment per named object.
    for m in _REMOVE_VERB_RE.finditer(q):
        stop = _REMOVE_STOP_RE.search(q, m.end())
        span_end = stop.start() if stop else len(q)
        chunk = q[m.end():span_end]
        if not chunk.strip():
            continue
        consumed.append((m.start(), span_end))
        for part in re.split(r"\band\b|,|&", chunk, flags=re.I):
            ref = _clean_ref(part)
            if len(ref) < 3 or not re.search(r"[a-z]", ref, re.I) or ref.lower() in _REF_PRONOUNS:
                continue
            if has_prior_selection:
                amendments.append(Amendment(ref=ref, new_qty=0))
            else:
                notes.append(f"remove '{ref[:40]}' ignored: no prior selection/cart to remove from.")
            if len(amendments) >= 4:
                break

    # (b) NAMED quantity: "reduce the Alpha Slim 3 to 20" -> qty amendment bound to the name reference.
    for m in _NAMED_QTY_RE.finditer(q):
        n = _to_int(m.group("n"))
        ref = _clean_ref(m.group("obj"))
        if n is None or not (1 <= n <= 500):
            continue
        if budget_span and budget_span[0] <= m.start("n") < budget_span[1]:
            continue  # that number is the budget
        consumed.append((m.start(), m.end()))
        if ref.lower() in _REF_PRONOUNS or len(ref) < 3:
            continue  # "make it 15" style stays on the bare-number/__last__ path below
        if has_prior_selection:
            amendments.append(Amendment(ref=ref, new_qty=n))
        else:
            notes.append(f"amend '{ref[:40]}'-to-{n} ignored: no prior selection to amend.")

    # (c) bare-number fallback ("actually make it 15") - positional __last__; numbers inside claimed
    # spans are skipped. One bare amendment per turn.
    for m in re.finditer(r"\b" + _NUM + r"\b", ql):
        n = _to_int(m.group(1))
        if n is None or not (1 <= n <= 500):
            continue
        if budget_span and budget_span[0] <= m.start() < budget_span[1]:
            continue  # this number IS the budget, not a quantity
        if any(a <= m.start() < b for a, b in consumed):
            continue  # claimed by a removal/named amendment above
        before = ql[max(0, m.start() - 30):m.start()]
        after = ql[m.end():m.end() + 18]
        # a quantity amendment: an amend cue precedes it AND it isn't immediately followed by a category noun
        if _AMEND_RE.search(before) and not re.match(r"\s+[a-z][a-z/\-]{2,}s\b", after):
            if has_prior_selection:
                amendments.append(Amendment(ref="__last__", new_qty=n))
            else:
                notes.append(f"amend-to-{n} ignored: no prior selection to amend (ask which item).")
            break  # one BARE amendment per turn (the buyer changes their mind once)
    amendments = amendments[:6]

    # ── gate new lines to a genuinely MULTI-intent "add-on" turn ─────────────────────────────────────
    # A new line only means something when the buyer is ADDING on top of something: there must be a prior
    # selection to add to, OR an in-turn signal that this is an add ("actually 15" amendment, a "for those"
    # scope cue, or an explicit add verb). A plain fresh search ("what laptops for work, I need 25") trips a
    # request cue but is SINGLE-intent — surfacing a new-line confirmation card there is noise (the bulk-query
    # false card GPT-5.5 flagged). Scoped turns keep their lines (the OR below), so budget binding is intact.
    if new_lines and not (has_prior_selection or amendments or scoped or _ADD_VERB_RE.search(ql)):
        notes.append("new-line categories dropped: plain single-intent search (no prior/amend/scope/add cue).")
        new_lines = []

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


# ── LLM binding layer (schema-constrained; validated by the same grammar rules) ──────────────────────────
def _needs_llm_binding(intents: TurnIntents, ql: str, has_prior_selection: bool) -> bool:
    """Call the LLM only when the deterministic parse likely MISSED an intent — a change signal with no
    amendment, or an add signal with no new line, or genuinely low confidence. A fully-captured turn keeps
    the free fast-path (no model call)."""
    if intents.confidence < 0.75:
        return True
    if has_prior_selection and _CHANGE_VERB_RE.search(ql) and not intents.amendments:
        return True
    if _ADD_VERB_RE.search(ql) and not intents.new_lines:
        return True
    return False


_LLM_BINDING_PROMPT = (
    "You extract a shopper's shopping intents from ONE message into STRICT JSON. Output ONLY the JSON object,"
    " no prose. Schema:\n"
    '{"amendments":[{"ref":"__last__ or a short product-name reference","new_qty":<int, 0 = remove>}],'
    '"new_lines":[{"category":"<short generic plural noun>","qty":<int or null>}],'
    '"budget_scopes":[{"applies_to":["__new__"],"budget_min":<int or null>,"budget_max":<int or null>}],'
    '"objection":"price" or null}\n'
    "Rules:\n"
    "- amendments: when the shopper changes the QUANTITY of an item they already have ('make it 15',"
    " 'reduce the Alpha Slim to 20') or REMOVES one ('get rid of the Alpha X1' -> new_qty 0). ref: '__last__'"
    " for it/that; else the product-name words they used (max 8 words, verbatim). One entry per item;"
    " up to 6. has_prior_selection={prior}; if false, emit NO amendment.\n"
    "- new_lines: each DISTINCT additional product category the shopper wants, with its quantity if stated"
    " ('3 monitors' -> qty 3; 'some headsets' -> qty null; 'a docking station' -> qty 1). Use short GENERIC"
    " category nouns (plural), never brands or models. qty must be 1..500 or null.\n"
    "- budget_scopes: a budget the shopper ties to the new items ('2000 for those', 'under 500 for the"
    " accessories', 'with the leftover budget') -> applies_to ['__new__']. Omit if no budget. Values are"
    " whole numbers >= 50.\n"
    "- objection: 'price' if they complain about cost, else null.\n"
    "- RELATIVE changes need the prior state: 'halve it' with prior qty 20 -> new_qty 10; 'double it' with"
    " prior qty 5 -> new_qty 10; 'cut it to 1000' about the BUDGET -> budget change, not a quantity.\n"
    "{context}"
    'Message: "{msg}"\nJSON:'
)


def _bind_with_llm(query: str, has_prior_selection: bool, llm_fn: LLMFn,
                   prior_context: Optional[Dict[str, Any]] = None) -> Optional[TurnIntents]:
    """Ask the injected LLM for the forced schema, then VALIDATE it with the deterministic rules. Returns a
    TurnIntents on success, or None on any failure (caller falls back to the deterministic parse).

    ``prior_context`` (optional, numbers + an opaque label only) is what makes RELATIVE language computable:
    "halve the order" is unanswerable without the prior qty — with {"qty": 20} in the prompt the model can
    emit new_qty=10, which the deterministic validator then re-checks like any other number."""
    ctx = ""
    if isinstance(prior_context, dict) and prior_context:
        bits = []
        if prior_context.get("qty") is not None:
            bits.append(f"quantity {int(prior_context['qty'])}")
        if prior_context.get("name"):
            bits.append(f"item '{str(prior_context['name'])[:60]}'")
        if prior_context.get("budget_max") is not None:
            bits.append(f"budget up to {int(prior_context['budget_max'])}")
        if bits:
            ctx = "Prior selection: " + ", ".join(bits) + ".\n"
        # the full cart (name x qty) lets the model bind NAMED refs to the right line, not just __last__
        lines = prior_context.get("lines")
        if isinstance(lines, list) and len(lines) > 1:
            rows = "; ".join(f"'{str(l.get('name'))[:50]}' x{l.get('qty')}"
                             for l in lines[:6] if isinstance(l, dict) and l.get("name"))
            if rows:
                ctx += "Cart lines: " + rows + ".\n"
    prompt = (_LLM_BINDING_PROMPT
              .replace("{prior}", "true" if has_prior_selection else "false")
              .replace("{context}", ctx)
              .replace("{msg}", str(query or "").replace('"', "'")[:400]))
    try:
        raw = llm_fn(prompt)
    except Exception:
        return None
    return _parse_llm_intents(raw, has_prior_selection)


def _parse_llm_intents(raw: Any, has_prior_selection: bool) -> Optional[TurnIntents]:
    """Parse + VALIDATE the model's JSON into TurnIntents. Every number is re-checked against the same rules
    the deterministic authorizer uses (qty 1..500, budget >= 50, ref __last__, no amendment without a prior).
    Any structural problem → None (never trust an unvalidated model plan)."""
    text = str(raw or "").strip()
    if not text:
        return None
    # tolerate a model that wraps the JSON in prose/code fences — grab the first {...} block
    if not text.startswith("{"):
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if not m:
            return None
        text = m.group(0)
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None

    amendments: List[Amendment] = []
    seen_refs: set = set()
    for a in (data.get("amendments") or [])[:6]:   # up to 6 line-ops per turn (removals + qty changes)
        if not isinstance(a, dict):
            continue
        nq = _to_int(a.get("new_qty"))
        ref = _clean_ref(str(a.get("ref") or "__last__"))
        if not ref or ref.lower() in ("__last__", "last", "it", "that"):
            ref = "__last__"
        # 0 (removal) is valid; anything else re-checked against the same 1..500 rule as the grammar
        if nq is None or not (0 <= nq <= 500) or not has_prior_selection:
            continue
        key = (ref.lower(), nq)
        if key in seen_refs:
            continue
        seen_refs.add(key)
        amendments.append(Amendment(ref=ref, new_qty=nq))

    new_lines: List[NewLine] = []
    seen: set = set()
    for nl in (data.get("new_lines") or [])[:8]:
        if not isinstance(nl, dict):
            continue
        cat = str(nl.get("category") or "").strip().lower()
        cat = re.sub(r"[^a-z0-9 /\-]", "", cat)[:40].strip()
        if not cat or cat in seen or cat.rstrip("s") in _STOP_NOUNS or cat in _STOP_NOUNS:
            continue
        q = _to_int(nl.get("qty"))
        if q is not None and not (1 <= q <= 500):
            q = None
        seen.add(cat)
        new_lines.append(NewLine(category=cat, qty=q))

    budget_scopes: List[BudgetScope] = []
    global_budget: Optional[Tuple[Optional[int], Optional[int]]] = None
    for b in (data.get("budget_scopes") or [])[:1]:
        if not isinstance(b, dict):
            continue
        bmin, bmax = _to_int(b.get("budget_min")), _to_int(b.get("budget_max"))
        bmin = bmin if (bmin is not None and bmin >= 50) else None
        bmax = bmax if (bmax is not None and bmax >= 50) else None
        if bmin is None and bmax is None:
            continue
        if new_lines:
            budget_scopes.append(BudgetScope(applies_to=("__new__",), budget_min=bmin, budget_max=bmax))
        else:
            global_budget = (bmin, bmax)

    objection = "price" if str(data.get("objection") or "").strip().lower() == "price" else None

    if not (amendments or new_lines or budget_scopes or global_budget or objection):
        return None   # the model added nothing usable → let the deterministic parse stand

    notes = ["parsed by LLM binding (schema-validated)"]
    # a mixed, money-changing turn always warrants confirmation.
    present = sum(bool(x) for x in (amendments, new_lines, budget_scopes or global_budget, objection))
    confidence = 0.7 if present >= 2 else 0.8
    return TurnIntents(amendments=amendments, new_lines=new_lines, budget_scopes=budget_scopes,
                       global_budget=global_budget, objection=objection, confidence=confidence, notes=notes)
