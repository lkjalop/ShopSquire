"""Read-only, case-bound supplier draft; no approval, enqueue or transport."""

from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError


def remaining_shortfall(db, *, tenant_id, case_id, revision, now=None):
    selection = (
        db.execute(
            text(
                "SELECT selection_id,requested_quantity FROM shopping_case_fulfillment_selections "
                "WHERE tenant_id=:tenant AND case_id=:case AND revision=:revision"
            ),
            dict(tenant=tenant_id, case=case_id, revision=revision),
        )
        .mappings()
        .first()
    )
    if not selection:
        raise ValueError("current_accepted_selection_required")
    selection_id = (
        str(selection["selection_id"]).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    )
    dialect = db.get_bind().dialect.name
    if dialect == "sqlite":
        live_expiry = "julianday(expires_at)>julianday(:now)"
    elif dialect == "postgresql":
        live_expiry = "CAST(expires_at AS TIMESTAMPTZ)>CAST(:now AS TIMESTAMPTZ)"
    else:
        raise ValueError("inventory_coverage_dialect_not_supported")
    covered = db.execute(
        text(
            "SELECT COALESCE(SUM(quantity),0) FROM inventory_reservation WHERE tenant_id=:tenant "
            "AND reservation_id LIKE :prefix ESCAPE '\\' AND (status IN ('shipped','returned') OR "
            "(status='reserved' AND (expires_at IS NULL OR " + live_expiry + ")))"
        ),
        dict(
            tenant=tenant_id,
            prefix="selection:" + selection_id + ":%",
            now=(now or datetime.now(timezone.utc)).isoformat(),
        ),
    ).scalar_one()
    return max(0, selection["requested_quantity"] - covered)


def shortfall_draft(db, *, tenant_id, case_id, revision, state, now=None, include_budget=True):
    quantity = state.get("requested_quantity")
    quantity = (
        quantity
        if (isinstance(quantity, int) and not isinstance(quantity, bool)) and quantity > 0
        else None
    )
    result = dict(
        tenant_id=tenant_id,
        case_id=case_id,
        case_revision=revision,
        requested_quantity=quantity,
        shortfall=None,
        recipient=None,
        subject="Stock shortfall enquiry",
        body="",
        status="provisional_draft",
        missing_inputs=["supplier_contact"],
        commerce_authority="none",
        dispatch_authorized=False,
    )
    selection = (
        db.execute(
            text(
                "SELECT preferred_sku,requested_quantity FROM shopping_case_fulfillment_selections "
                "WHERE tenant_id=:tenant AND case_id=:case AND revision=:revision"
            ),
            dict(tenant=tenant_id, case=case_id, revision=revision),
        )
        .mappings()
        .first()
    )
    if not quantity:
        result["missing_inputs"].append("requested_quantity")
    if not selection or selection["requested_quantity"] != quantity:
        result["missing_inputs"].append("current_accepted_selection")
    else:
        result["sku"] = selection["preferred_sku"]
        try:
            result["shortfall"] = remaining_shortfall(
                db, tenant_id=tenant_id, case_id=case_id, revision=revision, now=now
            )
        except SQLAlchemyError:
            # The caller owns a dedicated read session; a failed provider is
            # reported explicitly and cannot guess an exact stock shortfall.
            result["missing_inputs"].append("verified_inventory_coverage")
    quantity_label = f"{quantity} units" if quantity else "the quantity still to be confirmed"
    if result["shortfall"] is not None:
        result["status"] = "draft_ready" if result["shortfall"] else "no_shortfall"
        if not result["shortfall"]:
            result["body"] = (
                f"The current request for {quantity_label} is fully covered; no additional supplier enquiry is needed."
            )
            return _versioned(result, include_budget=include_budget)
        request = (
            f"Please quote availability, price and lead time for {result['shortfall']} units "
            f"of {selection['preferred_sku']}, the remaining shortfall against our {quantity_label} request."
        )
    else:
        request = (
            f"Please confirm availability, price and lead time toward our request for {quantity_label}. "
            "The exact shortfall is pending confirmation of the accepted product and current inventory coverage."
        )
    details = []
    for destination in state.get("destinations") or []:
        if isinstance(destination, dict) and destination.get("location_ref"):
            details.append(
                f"Delivery: {destination['location_ref']} ({destination['quantity']} units)."
            )
    budget = state.get("budget") or {}
    if (
        include_budget
        and (
            isinstance(budget.get("amount_minor"), int)
            and not isinstance(budget.get("amount_minor"), bool)
        )
        and budget.get("currency")
    ):
        scope = {
            "per_unit": "per unit",
            "total": "total",
            "unknown": "(scope to be confirmed)",
        }.get(budget.get("scope"))
        if scope:
            details.append(
                f"Budget: {budget['currency']} {budget['amount_minor'] / 100:.2f} {scope}."
            )
    temporal = state.get("temporal") or {}
    if temporal.get("original_expression"):
        details.append(
            "Requested delivery deadline: "
            + temporal["original_expression"]
            + " ("
            + str(temporal.get("resolution_status") or "unresolved")
            + "). Please confirm feasibility."
        )
    result["body"] = "\n".join(
        [
            "Hello,",
            "",
            request,
            *details,
            "",
            "Please include freight costs and any minimum order quantity. This enquiry does not authorize a purchase.",
        ]
    )
    return _versioned(result, include_budget=include_budget)


def _versioned(result, *, include_budget):
    """Content-address the composition; recipient binding is reviewed separately."""
    from src.app.services.supplier_enquiry_drafts import seal

    result["draft_artifact"] = seal(
        {
            "schema_version": "supplier-message-draft-v1",
            **{
                key: result.get(key)
                for key in (
                    "tenant_id",
                    "case_id",
                    "case_revision",
                    "requested_quantity",
                    "shortfall",
                    "sku",
                    "subject",
                    "body",
                )
            },
            "include_budget": bool(include_budget),
            "commerce_authority": "none",
        }
    )
    return result
