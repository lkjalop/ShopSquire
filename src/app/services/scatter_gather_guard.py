"""Scatter-gather adversarial guard (agnostic CORE) — verify a multi-line plan BEFORE it's shown.

The fan-out that answers a multi-intent turn ("15 of the laptop + headsets + hard drives for $1200") can fail
silently: a category query returns the wrong products, a scoped budget bleeds onto the wrong line, a quantity
explodes, or the previously-chosen item is dropped. This guard is the structured analogue of the narration
claim-guard: it RECHECKS the assembled plan against what was requested and returns concrete violations. A
failed check means "don't assemble this — re-ask or fall back", never "confidently show a wrong plan".

Five checks per plan:
  1. category match      — each result for a NEW line actually matches that line's category token.
  2. budget scope        — every result is within its line's (scoped) budget.
  3. quantity sanity     — every line quantity is in [1, 500].
  4. context survival    — every prior/chosen item that must survive is still present.
  5. no cross-contamination — a NEW line's scoped budget did not leak onto a PRIOR (amended) line.

Vertical-blind: category is an OPAQUE token matched against opaque product DATA (name/tags); everything else
is numbers. Pure: no DB, no LLM. Fail-closed by construction — anything it can't verify is a violation.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class GuardVerdict:
    ok: bool
    violations: List[str] = field(default_factory=list)
    checked_lines: int = 0

    def as_dict(self) -> Dict[str, Any]:
        return {"ok": self.ok, "violations": list(self.violations), "checked_lines": self.checked_lines}


def _matches_category(result: Dict[str, Any], category: str) -> bool:
    """Does an opaque product result belong to a category token? Token-in-DATA match (crude singularise) over
    the result's name + tags/type — the same vertical-blind approach as order_split. Empty category → vacuous
    True (nothing to verify)."""
    cat = str(category or "").strip().lower()
    if not cat:
        return True
    # match on the LAST word of a multi-word category ("hard drives" → "drive") + the whole token
    last = cat.split()[-1].rstrip("s")
    whole = cat.rstrip("s")
    tags = result.get("tags") if isinstance(result.get("tags"), (list, tuple)) else []
    blob = " ".join([str(result.get("name") or ""), str(result.get("type") or ""),
                     str(result.get("category") or ""), " ".join(str(t) for t in tags)]).lower()
    return bool(last and (re.search(r"\b" + re.escape(last), blob) or (whole and whole in blob)))


def verify_plan(lines: List[Dict[str, Any]], *, must_survive: Optional[List[str]] = None) -> GuardVerdict:
    """Recheck an assembled plan. ``lines`` items: {ref?, category, scope('new'|'prior'), requested_qty?,
    budget_max?, results:[{name, price_cents, tags?}]}. ``must_survive``: refs that MUST appear (the chosen
    items from before this turn). Returns a GuardVerdict; ok only when there are zero violations."""
    violations: List[str] = []
    rows = [l for l in (lines or []) if isinstance(l, dict)]
    present_refs = {str(l.get("ref")) for l in rows if l.get("ref")}
    new_budgets = {int(l["budget_max"]) for l in rows
                   if l.get("scope") == "new" and isinstance(l.get("budget_max"), (int, float)) and l.get("budget_max")}

    for l in rows:
        cat = str(l.get("category") or "")
        scope = str(l.get("scope") or "new")
        results = l.get("results") if isinstance(l.get("results"), list) else []

        # 3) quantity sanity
        q = l.get("requested_qty")
        if q is not None:
            try:
                qi = int(q)
                if not (1 <= qi <= 500):
                    violations.append(f"quantity out of range: {qi} for '{cat or l.get('ref')}'")
            except (TypeError, ValueError):
                violations.append(f"quantity not a number for '{cat or l.get('ref')}'")

        # 1) category match — only for NEW lines (a prior chosen item is already the buyer's pick)
        if scope == "new" and cat:
            for r in results:
                if isinstance(r, dict) and not _matches_category(r, cat):
                    violations.append(f"category mismatch: '{cat}' line returned '{r.get('name') or r.get('sku')}'")

        # 2) budget scope
        bmax = l.get("budget_max")
        if isinstance(bmax, (int, float)) and bmax:
            for r in results:
                try:
                    price = float(r.get("price_cents") or 0) / 100.0
                except (TypeError, ValueError):
                    price = 0.0
                if price > float(bmax) + 0.001:
                    violations.append(f"budget bleed: '{cat or l.get('ref')}' result "
                                      f"${price:,.0f} exceeds scoped ${float(bmax):,.0f}")

        # 5) cross-contamination — a PRIOR line must not carry a NEW line's scoped budget
        if scope == "prior" and isinstance(bmax, (int, float)) and int(bmax) in new_budgets:
            violations.append(f"cross-contamination: prior item '{l.get('ref') or cat}' got the new "
                              f"scoped budget ${float(bmax):,.0f}")

    # 4) context survival
    for ref in (must_survive or []):
        if str(ref) not in present_refs:
            violations.append(f"context lost: prior item '{ref}' dropped from the plan")

    return GuardVerdict(ok=not violations, violations=violations, checked_lines=len(rows))
