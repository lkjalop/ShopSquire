"""Read canonical case budgets and describe excluded catalog alternatives without qualification."""
import json
import logging
from typing import Any
from sqlalchemy import select, text
from src.app.models.orm import ProductConfiguration

logger = logging.getLogger("shopsquire.catalog_shortfall")

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
