"""Reconcile an explicit single-item budget with retained quantity."""
from dataclasses import replace


def apply_single_item_budget(decision, *, parsed_budget, query, commercial_quantity):
    if (parsed_budget is not None and parsed_budget.describes_single_item(query)
            and not decision.quantity_explicit and commercial_quantity is None):
        return replace(decision,quantity=1,quantity_explicit=True,budget_scope='per_unit')
    return decision
