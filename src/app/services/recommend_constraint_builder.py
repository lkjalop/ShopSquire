"""Budget-constraint resolution (agnostic CORE) — the ordered merge table for the money slots.

HISTORY: a previous extraction of this module went STALE — suggest() never called it, the inline copy
kept evolving, and six budget bugs clustered exactly there (fresh parse stomped by decayed memory,
reversed bands, floors silently re-opened/lost). This rewrite replaces the dead code with the two pure
functions suggest() now ACTUALLY calls, each returning PROVENANCE so the decision trace shows one
`budget_resolution` event ("slot ← source") instead of scattered writes.

  initial_budget()         — the or-chain init: request param > fresh parse > nlp prefs > decayed
                             memory > confirmed slots. "Request param beats everything; a fresh parse
                             beats any memory."
  apply_budget_revisions() — the post-parse rules, in order: one-sided reset (an "under X" turn clears
                             a stale floor; an "over X" turn clears a stale ceiling), inverted-band
                             repair, spec-only-turn clear, floor-carry on an explicit RAISE (never on a
                             cut verb), memory reload for deictic follow-ups.

Vertical-blind: integers, generic English cue words, no product vocabulary. Pure — no I/O, no DB;
the caller owns trace emission and timing. Property-tested in tests/services/test_budget_resolution.py.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, List, Optional, Tuple

Prov = Tuple[str, str, Optional[int]]   # (slot, source, value)


@dataclass(frozen=True)
class BudgetResolution:
    budget_min: Optional[int]
    budget_max: Optional[int]
    provenance: List[Prov] = field(default_factory=list)


def _num(v: Any) -> Optional[int]:
    if isinstance(v, bool) or v is None:
        return None
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def initial_budget(
    *,
    request_min: Any = None, request_max: Any = None,
    parsed_min: Any = None, parsed_max: Any = None,
    nlp_min: Any = None, nlp_max: Any = None,
    decayed_min: Any = None, decayed_max: Any = None,
    confirmed_min: Any = None, confirmed_max: Any = None,
) -> BudgetResolution:
    """The init or-chain as an explicit merge table. Each slot resolves independently to the FIRST
    non-null source in precedence order; provenance records which source won."""
    prov: List[Prov] = []

    def _resolve(slot: str, *sources: "Tuple[str, Any]") -> Optional[int]:
        for name, raw in sources:
            v = _num(raw)
            if v is not None:
                prov.append((slot, name, v))
                return v
        prov.append((slot, "none", None))
        return None

    bmin = _resolve("budget_min", ("request", request_min), ("parsed", parsed_min),
                    ("nlp", nlp_min), ("decayed", decayed_min), ("confirmed", confirmed_min))
    bmax = _resolve("budget_max", ("request", request_max), ("parsed", parsed_max),
                    ("nlp", nlp_max), ("decayed", decayed_max), ("confirmed", confirmed_max))
    return BudgetResolution(bmin, bmax, prov)


_ONE_SIDED_MAX_CUES = ("under", "below", "up to", "max")
_ONE_SIDED_MIN_CUES = ("above", "over", "minimum", "at least")
_UPDATE_CUE_RE = re.compile(r"\b(now|actually|instead|change[d]?|update[d]?)\b")
_CUT_VERB_RE = re.compile(r"\b(cut|drop|lower|reduce|cheaper)\b")


def apply_budget_revisions(
    *,
    current_min: Any, current_max: Any,
    parsed_min: Any, parsed_max: Any,
    query_lower: str,
    asks_budget: bool,
    explicit_constraint_update: bool,
    references_prior: bool,
    followup_explain: bool,
    decayed_min: Any = None,
    nlp_min: Any = None, nlp_max: Any = None,
) -> BudgetResolution:
    """The post-parse revision rules, applied in a FIXED order with provenance. Pure."""
    q = str(query_lower or "")
    bmin, bmax = _num(current_min), _num(current_max)
    p_min, p_max = _num(parsed_min), _num(parsed_max)
    prov: List[Prov] = []

    if asks_budget:
        # 1) one-sided reset: "under $900" clears a stale floor; "above $2000" clears a stale ceiling.
        if p_max is not None and p_min is None and any(t in q for t in _ONE_SIDED_MAX_CUES):
            if bmin is not None:
                prov.append(("budget_min", "one_sided_reset", None))
            bmin = None
        if p_min is not None and p_max is None and any(t in q for t in _ONE_SIDED_MIN_CUES):
            if bmax is not None:
                prov.append(("budget_max", "one_sided_reset", None))
            bmax = None
        # 2) inverted-band repair: floor > ceiling can only be a mis-merge — resolve by cue, else swap.
        if bmin is not None and bmax is not None and float(bmin) > float(bmax):
            if any(t in q for t in _ONE_SIDED_MAX_CUES):
                prov.append(("budget_min", "inverted_reset", None))
                bmin = None
            elif any(t in q for t in _ONE_SIDED_MIN_CUES):
                prov.append(("budget_max", "inverted_reset", None))
                bmax = None
            else:
                prov.append(("budget_min", "inverted_swap", bmax))
                prov.append(("budget_max", "inverted_swap", bmin))
                bmin, bmax = bmax, bmin

    # 3) spec-only refinement turn: an explicit constraint update that neither asks about budget nor
    #    references earlier results must NOT inherit the prior envelope.
    if (explicit_constraint_update and not asks_budget and not references_prior
            and p_max is None and p_min is None):
        if bmin is not None or bmax is not None:
            prov.append(("budget_min", "spec_turn_clear", None))
            prov.append(("budget_max", "spec_turn_clear", None))
        bmin = None
        bmax = None

    # 4) floor-carry on an explicit RAISE: "actually budget is now 1800 max" keeps the remembered floor
    #    (never re-opens the cheap tier the buyer excluded). Never on a cut verb — a cut resets the floor.
    if (p_max is not None and p_min is None
            and _UPDATE_CUE_RE.search(q) and not _CUT_VERB_RE.search(q)):
        d_min = _num(decayed_min)
        if d_min is not None and float(d_min) < float(p_max):
            prov.append(("budget_min", "floor_carry", d_min))
            bmin = d_min

    # 5) memory reload for deictic follow-ups only ("those/that" / explain turns with no fresh budget).
    if (not asks_budget and p_max is None and p_min is None
            and (references_prior or followup_explain)):
        n_min, n_max = _num(nlp_min), _num(nlp_max)
        if n_max is not None:
            prov.append(("budget_max", "memory_reload", n_max))
            bmax = n_max
        if n_min is not None:
            prov.append(("budget_min", "memory_reload", n_min))
            bmin = n_min

    return BudgetResolution(bmin, bmax, prov)
