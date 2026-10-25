"""Reconcile an explicit single-item budget with retained quantity."""
from dataclasses import replace


def apply_single_item_budget(decision, *, parsed_budget, query, commercial_quantity):
    if (parsed_budget is not None and parsed_budget.describes_single_item(query)
            and not decision.quantity_explicit and commercial_quantity is None):
        return replace(decision,quantity=1,quantity_explicit=True,budget_scope='per_unit')
    return decision


def apply_relative_budget(envelope):
    """Apply a literal delta only to the immutable accepted budget."""
    from src.app.services.budget_grammar import parse_budget_delta

    # A relative budget instruction is authorized only against the immutable
    # accepted session value. Apply it before routing/retrieval so every later
    # stage sees the same bounded envelope; never reinterpret the delta as an
    # absolute cap.
    _accepted_before_route = (envelope.session or {}).get("accepted_constraints") or {}
    _budget_delta = parse_budget_delta(envelope.query)
    _prior_budget_max = _accepted_before_route.get("budget_max_cents")
    if _budget_delta is not None and _prior_budget_max is not None:
        try:
            _updated_budget_max = int(_prior_budget_max) + (_budget_delta * 100)
            _prior_budget_min = _accepted_before_route.get("budget_min_cents")
            _updated_budget_min = (
                int(_prior_budget_min) + (_budget_delta * 100)
                if _prior_budget_min is not None
                else None
            )
        except (TypeError, ValueError):
            _updated_budget_max = 0
            _updated_budget_min = None
        if _updated_budget_max > 0:
            envelope = replace(
                envelope,
                budget_min_cents=(
                    _updated_budget_min
                    if _updated_budget_min is not None and _updated_budget_min > 0
                    else None
                ),
                budget_max_cents=_updated_budget_max,
            )

    return envelope
