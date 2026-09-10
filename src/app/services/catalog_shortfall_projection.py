"""Read canonical case budgets and describe excluded catalog alternatives without qualification."""
import json
import logging
from typing import Any
from sqlalchemy import select, text
from src.app.models.orm import ProductConfiguration

logger = logging.getLogger("shopsquire.catalog_shortfall")


def stretch_consent_receipt(consent, *, case_id, revision, budget, reviewer):
    """One acceptance operation only; this never amends the durable buyer budget."""
    if consent is None:
        return None
    cap = consent.get('unit_cap_cents')
    if consent.get('expected_revision') != revision:
        raise ValueError('stretch_revision_conflict')
    if budget is None or isinstance(cap, bool) or not isinstance(cap, int) or cap <= budget:
        raise ValueError('stretch_requires_known_budget_and_higher_cap')
    from datetime import datetime, timezone
    return {'case_id': case_id, 'case_revision': revision, 'reviewer_id': reviewer,
            'recorded_at': datetime.now(timezone.utc).isoformat(),
            'original_unit_budget_cents': budget, 'unit_cap_cents': cap,
            'currency': 'AUD', 'scope': 'this_acceptance_only', 'commerce_authority': 'none'}


def acceptance_budget(state: dict[str, Any]) -> tuple[int | None, int]:
    """Return a per-unit allowance, never reinterpret a bulk total as unit money."""
    procurement = state.get('procurement_case_state') or {}
    if not isinstance(procurement, dict):
        raise ValueError('budget_state_invalid')
    quantity = procurement.get('requested_quantity', 1)
    if quantity is None:
        quantity = 1
    if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 1:
        raise ValueError('quantity_unresolved')
    budget = procurement.get('budget') or {}
    if not isinstance(budget, dict):
        raise ValueError('budget_state_invalid')
    amount = budget.get('amount_minor')
    if amount is None:
        read_budget = (state.get('turn_read_model') or {}).get('canonical_budget') or {}
        if read_budget.get('budget_max') is not None:
            amount = read_budget['budget_max'] * 100
    if amount is None:
        return None, quantity
    if isinstance(amount, bool) or not isinstance(amount, int) or amount < 0:
        raise ValueError('budget_amount_invalid')
    if budget.get('currency') not in (None, 'AUD'):
        raise ValueError('budget_currency_conversion_required')
    scope = budget.get('scope')
    if scope == 'total':
        if not procurement.get('requested_quantity'):
            raise ValueError('budget_quantity_unresolved')
        amount //= quantity
    elif scope != 'per_unit' and quantity > 1:
        raise ValueError('budget_scope_unresolved')
    return amount, quantity


def read_acceptance_budget(db, *, tenant_id: str, case_id: str, expected_revision: int):
    rows = db.execute(text(
        'SELECT version,state_json FROM conversation_case_state '
        'WHERE tenant_id=:tenant_id AND case_id=:case_id'
    ), {'tenant_id': tenant_id, 'case_id': case_id}).all()
    if not rows:
        return None, 1
    if len(rows) != 1 or int(rows[0][0]) != expected_revision:
        raise ValueError('budget_case_revision_conflict')
    raw = rows[0][1]
    state = json.loads(raw) if isinstance(raw, str) else raw
    if not isinstance(state, dict):
        raise ValueError('budget_state_invalid')
    return acceptance_budget(state)

def _case_budget_cents(db, *, tenant_id: str, case_id: str) -> int | None:
    """Read the latest canonical case budget without reparsing buyer prose."""
    try:
        row = db.execute(text(
            "SELECT state_json FROM conversation_case_state "
            "WHERE tenant_id=:tenant_id AND case_id=:case_id "
            "ORDER BY version DESC LIMIT 1"
        ), {"tenant_id": tenant_id, "case_id": case_id}).first()
        if not row:
            return None
        state = row[0]
        if isinstance(state, str):
            state = json.loads(state)
        if not isinstance(state, dict):
            return None
        procurement_budget = (
            (state.get("procurement_case_state") or {}).get("budget")
            if isinstance(state.get("procurement_case_state"), dict) else None
        )
        if isinstance(procurement_budget, dict):
            amount = procurement_budget.get("amount_minor")
            if amount is not None:
                return max(0, int(amount))
        read_budget = (
            (state.get("read_model") or {}).get("canonical_budget")
            if isinstance(state.get("read_model"), dict) else None
        )
        if isinstance(read_budget, dict):
            amount = read_budget.get("budget_max")
            if amount is not None:
                return max(0, int(amount) * 100)
    except (TypeError, ValueError, json.JSONDecodeError):
        logger.warning("case budget projection was malformed", exc_info=True)
    except Exception:
        logger.warning("case budget projection unavailable", exc_info=True)
    return None


def _catalog_shortfall_alternative(
    db, *, tenant_id: str, exclusion: dict[str, Any] | None,
    budget_cents: int | None,
) -> tuple[dict[str, Any], int | None]:
    """Describe the nearest excluded SKU and its price gap, without qualifying it."""
    if not isinstance(exclusion, dict) or not exclusion.get("sku"):
        return {}, None
    sku = str(exclusion["sku"])
    row = db.execute(select(ProductConfiguration).where(
        ProductConfiguration.tenant_id == tenant_id,
        ProductConfiguration.sku == sku,
    ).limit(1)).scalar_one_or_none()
    alternative = {
        "sku": sku,
        "reason": exclusion.get("reason"),
        "status": "not_qualified_or_unavailable",
    }
    gap = None
    if row is not None:
        alternative.update({
            "title": row.title,
            "price_cents": int(row.price_cents),
            "currency": row.currency,
        })
        if budget_cents is not None:
            gap = max(0, int(row.price_cents) - int(budget_cents))
    return alternative, gap
