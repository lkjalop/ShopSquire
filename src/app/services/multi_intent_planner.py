"""Multi-intent planner (agnostic CORE) — the scatter-gather orchestration for a mixed buyer turn.

Ties the P0 pieces together into ONE bounded flow:
  1. decompose the turn (intent_decomposer) → amendments + new lines + scoped budget + objection;
  2. AMEND the prior/chosen item's quantity (bind "__last__" to the last shortlisted item);
  3. FAN OUT for each new category line with the SCOPED budget (search_fn injected — the caller supplies the
     real recommend engine; tests inject a stub) — the "scatter";
  4. ASSEMBLE the plan (prior + new lines) — the "gather";
  5. VERIFY it adversarially (scatter_gather_guard) BEFORE returning;
  6. decide whether a CONFIRMATION card is needed (low decompose confidence OR any guard violation) — never
     silently apply a mixed, money-changing turn.

Vertical-blind: categories/refs are opaque; the injected ``search_fn(category, budget_max)`` owns catalog
access. Pure orchestration otherwise (no DB, no LLM here). The prior laptop keeps its own budget; the scoped
budget only ever attaches to NEW lines — the guard proves it.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from src.app.services.intent_decomposer import decompose_turn
from src.app.services.scatter_gather_guard import verify_plan


def plan_turn(
    query: str,
    *,
    prior_lines: Optional[List[Dict[str, Any]]] = None,
    search_fn: Callable[[str, Optional[int]], List[Dict[str, Any]]],
    confirm_below: float = 0.8,
    llm_fn: Optional[Callable[[str], str]] = None,
    intents: Optional[Any] = None,
) -> Dict[str, Any]:
    """Plan a multi-intent turn. ``prior_lines``: the chosen/shortlisted items BEFORE this turn, newest last —
    each {ref, category?, requested_qty, budget_max?, results?}; the LAST is the "__last__" amendment target.
    ``search_fn(category, budget_max)`` returns candidate results for a new line within the scoped budget.
    Returns {intents, plan, verdict, needs_confirmation, objection_angle}. Never raises."""
    prior = [dict(p) for p in (prior_lines or []) if isinstance(p, dict)]
    # accept a pre-decomposed plan (so the caller's probe + this call don't double the LLM binding); else decompose.
    if intents is None:
        intents = decompose_turn(query, has_prior_selection=bool(prior), llm_fn=llm_fn)

    lines: List[Dict[str, Any]] = []

    # 1) prior lines carried forward — apply a "__last__" amendment to the LAST prior item's quantity
    amend_qty: Optional[int] = None
    for a in intents.amendments:
        if a.ref == "__last__":
            amend_qty = a.new_qty
    for i, p in enumerate(prior):
        row = dict(p)
        row["scope"] = "prior"
        # `amended` is True ONLY for the line this turn actually changed the qty of. A carried-forward,
        # unchanged prior line must NOT be presented as an amendment (else the UI shows a spurious
        # "Change X quantity to N" and confirming it would apply/add an item the buyer never asked to change).
        row["amended"] = bool(amend_qty is not None and i == len(prior) - 1)
        if row["amended"]:
            row["requested_qty"] = amend_qty            # 20 → 15 on the chosen laptop
        lines.append(row)

    # 2) the scoped budget applies to NEW lines only (the prior laptop keeps its own budget)
    scoped_max: Optional[int] = None
    scoped_min: Optional[int] = None
    for b in intents.budget_scopes:
        if "__new__" in b.applies_to:
            scoped_max, scoped_min = b.budget_max, b.budget_min

    # 3+4) scatter over the new category lines, gather results within the scoped budget
    warnings: List[str] = []
    for nl in intents.new_lines:
        try:
            results = search_fn(nl.category, scoped_max) or []
        except Exception as exc:  # a search failure is a SOFT failure — surface it, don't hide an empty line
            results = []
            warnings.append(f"search failed for '{nl.category}': {str(exc)[:120]}")
        lines.append({"category": nl.category, "scope": "new", "requested_qty": nl.qty,
                      "budget_min": scoped_min, "budget_max": scoped_max, "results": results})

    # 5) adversarial verification — the prior items MUST survive
    must_survive = [str(p.get("ref")) for p in prior if p.get("ref")]
    verdict = verify_plan(lines, must_survive=must_survive)

    # 6) confirm on low confidence OR any violation — never silently apply a mixed money-changing turn
    needs_confirmation = bool(intents.confidence < confirm_below or not verdict.ok)

    # tie in the support lane: a price objection → the phrasing angle to reframe with
    objection_angle = None
    if intents.objection == "price":
        try:
            from src.app.services.support_response_policy import objection_response
            objection_angle = objection_response("price").response_angle   # → "value"
        except Exception:
            objection_angle = "value"

    return {"intents": intents.as_dict(), "plan": lines, "verdict": verdict.as_dict(),
            "needs_confirmation": needs_confirmation or bool(warnings), "objection_angle": objection_angle,
            "warnings": warnings}
