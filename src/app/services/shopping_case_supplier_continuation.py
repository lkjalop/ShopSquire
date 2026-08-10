"""Persisted same-case fulfilment selection and buyer-safe offer projection.

This service never sends an RFQ and never mutates a cart.  It records a buyer's
selected continuation, normalizes already-existing or deterministic fixture
offers, and resolves the exact SKU/quantity that a guarded cart plan may use
after a separate revision-bound confirmation.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any, Literal, Sequence

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select, update

from src.app.models.orm import ShoppingCaseFulfillmentSelection


Choice = Literal[
    "split_delivery", "wait_preferred", "next_best_now", "supplier_enquiry", "substitute",
]


class SupplierOfferInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_type: Literal["existing_procurement_case", "deterministic_certification_fixture"]
    source_reference: str = Field(min_length=1, max_length=200)
    supplier_reference: str = Field(min_length=1, max_length=200)
    offered_sku: str = Field(min_length=1, max_length=120)
    relationship: Literal["exact", "compatible_substitute"]
    quantity_available: int = Field(ge=0, le=1_000_000)
    lead_time_days: int | None = Field(default=None, ge=0, le=3650)
    unit_price_cents: int | None = Field(default=None, ge=0, le=1_000_000_000)
    currency: str = Field(default="AUD", min_length=3, max_length=3)
    validity_expires_at: str | None = Field(default=None, max_length=80)


class BuyerSafeSupplierOffer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    offer_id: str
    offered_sku: str
    relationship: Literal["exact", "compatible_substitute"]
    quantity_available: int
    lead_time_days: int | None
    unit_price_cents: int | None
    currency: str
    validity_expires_at: str | None
    provenance: dict[str, str]
    supplier_send: Literal["not_performed"] = "not_performed"
    purchase_commitment: Literal[False] = False
    response_status: Literal["accepted", "rejected", "conditional", "late", "unverified"] = "unverified"
    response_reason: str = "Legacy response was not normalized against quantity and deadline."


class FulfillmentSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    selection_id: str
    case_id: str
    revision: int
    status: Literal["selected", "cart_applied"]
    choice: Choice
    preferred_sku: str
    requested_quantity: int
    available_now: int
    offers: list[BuyerSafeSupplierOffer]
    selected_offer_id: str | None = None
    cart_plan_id: str | None = None
    cart_result: dict[str, Any] | None = None


def normalize_supplier_offers(
    rows: Sequence[SupplierOfferInput], *, requested_quantity: int | None = None,
    available_now: int = 0, deadline_days: int | None = None,
) -> list[BuyerSafeSupplierOffer]:
    offers: list[BuyerSafeSupplierOffer] = []
    for row in rows:
        material = (
            f"{row.source_type}|{row.source_reference}|{row.supplier_reference}|"
            f"{row.offered_sku}|{row.relationship}|{row.quantity_available}|{row.lead_time_days}"
        )
        if row.quantity_available == 0:
            response_status = "rejected"
            response_reason = "Supplier reported no available quantity."
        elif row.relationship == "compatible_substitute":
            response_status = "conditional"
            response_reason = "Supplier proposed a substitute; workload fit and buyer acceptance are required."
        elif deadline_days is not None and row.lead_time_days is not None \
                and row.lead_time_days > deadline_days:
            response_status = "late"
            response_reason = f"Supplier lead time of {row.lead_time_days} days misses the {deadline_days}-day window."
        elif requested_quantity is not None \
                and available_now + row.quantity_available < requested_quantity:
            response_status = "conditional"
            response_reason = "Supplier quantity does not close the full verified shortfall."
        else:
            response_status = "accepted"
            response_reason = "Supplier response covers the required exact-configuration quantity within the stated window."
        offers.append(BuyerSafeSupplierOffer(
            offer_id="offer-" + hashlib.sha256(material.encode()).hexdigest()[:20],
            offered_sku=row.offered_sku,
            relationship=row.relationship,
            quantity_available=row.quantity_available,
            lead_time_days=row.lead_time_days,
            unit_price_cents=row.unit_price_cents,
            currency=row.currency.upper(),
            validity_expires_at=row.validity_expires_at,
            provenance={
                "source_type": row.source_type,
                "source_reference": row.source_reference,
                "supplier_reference": row.supplier_reference,
            },
            response_status=response_status,
            response_reason=response_reason,
        ))
    return offers


def certification_fixture_offers(
    *, case_id: str, preferred_sku: str, substitute_sku: str | None,
    requested_quantity: int, available_now: int,
) -> list[SupplierOfferInput]:
    """Deterministic non-network offers used only by the canonical certification journey."""

    remaining = max(0, requested_quantity - available_now)
    rows = [SupplierOfferInput(
        source_type="deterministic_certification_fixture",
        source_reference=f"{case_id}:fixture-rfq-response:preferred",
        supplier_reference="fixture-supplier-preferred",
        offered_sku=preferred_sku,
        relationship="exact",
        quantity_available=remaining,
        lead_time_days=8,
        unit_price_cents=585_000,
    ), SupplierOfferInput(
        source_type="deterministic_certification_fixture",
        source_reference=f"{case_id}:fixture-rfq-response:unavailable",
        supplier_reference="fixture-supplier-unavailable",
        offered_sku=preferred_sku,
        relationship="exact",
        quantity_available=0,
        lead_time_days=None,
        unit_price_cents=None,
    )]
    if substitute_sku:
        rows.append(SupplierOfferInput(
            source_type="deterministic_certification_fixture",
            source_reference=f"{case_id}:fixture-rfq-response:substitute",
            supplier_reference="fixture-supplier-substitute",
            offered_sku=substitute_sku,
            relationship="compatible_substitute",
            quantity_available=requested_quantity,
            lead_time_days=2,
            unit_price_cents=530_000,
        ))
    rows.append(SupplierOfferInput(
        source_type="deterministic_certification_fixture",
        source_reference=f"{case_id}:fixture-rfq-response:late",
        supplier_reference="fixture-supplier-late",
        offered_sku=preferred_sku,
        relationship="exact",
        quantity_available=requested_quantity,
        lead_time_days=21,
        unit_price_cents=590_000,
    ))
    return rows


def _decode(row: ShoppingCaseFulfillmentSelection) -> FulfillmentSelection:
    return FulfillmentSelection(
        selection_id=row.selection_id, case_id=row.case_id,
        revision=int(row.revision), status=row.status, choice=row.choice,
        preferred_sku=row.preferred_sku,
        requested_quantity=int(row.requested_quantity),
        available_now=int(row.available_now),
        offers=[BuyerSafeSupplierOffer.model_validate(item) for item in (row.offers_json or [])],
        selected_offer_id=row.selected_offer_id,
        cart_plan_id=row.cart_plan_id,
        cart_result=dict(row.cart_result_json) if row.cart_result_json else None,
    )


def get_fulfillment_selection(
    db, *, tenant_id: str, case_id: str, selection_id: str, uid: str,
) -> FulfillmentSelection | None:
    row = db.execute(select(ShoppingCaseFulfillmentSelection).where(
        ShoppingCaseFulfillmentSelection.tenant_id == tenant_id,
        ShoppingCaseFulfillmentSelection.case_id == case_id,
        ShoppingCaseFulfillmentSelection.selection_id == selection_id,
        ShoppingCaseFulfillmentSelection.uid == uid,
    )).scalar_one_or_none()
    return _decode(row) if row else None


def get_confirmation_replay(
    db, *, tenant_id: str, case_id: str, selection_id: str, uid: str,
    idempotency_key: str,
) -> FulfillmentSelection | None:
    row = db.execute(select(ShoppingCaseFulfillmentSelection).where(
        ShoppingCaseFulfillmentSelection.tenant_id == tenant_id,
        ShoppingCaseFulfillmentSelection.case_id == case_id,
        ShoppingCaseFulfillmentSelection.selection_id == selection_id,
        ShoppingCaseFulfillmentSelection.uid == uid,
        ShoppingCaseFulfillmentSelection.confirmation_idempotency_key == idempotency_key,
    )).scalar_one_or_none()
    return _decode(row) if row and row.cart_result_json else None


def select_fulfillment_option(
    db, *, tenant_id: str, case_id: str, uid: str, expected_revision: int,
    choice: Choice, preferred_sku: str, requested_quantity: int, available_now: int,
    idempotency_key: str, offers: Sequence[SupplierOfferInput],
    deadline_days: int | None = None,
) -> tuple[FulfillmentSelection | None, str | None]:
    replay = db.execute(select(ShoppingCaseFulfillmentSelection).where(
        ShoppingCaseFulfillmentSelection.tenant_id == tenant_id,
        ShoppingCaseFulfillmentSelection.case_id == case_id,
        ShoppingCaseFulfillmentSelection.selection_idempotency_key == idempotency_key,
    )).scalar_one_or_none()
    if replay:
        return _decode(replay), None
    current = db.execute(select(func.coalesce(func.max(
        ShoppingCaseFulfillmentSelection.revision,
    ), 0)).where(
        ShoppingCaseFulfillmentSelection.tenant_id == tenant_id,
        ShoppingCaseFulfillmentSelection.case_id == case_id,
    )).scalar_one()
    if int(current) != expected_revision:
        return None, f"stale_fulfillment_revision:{current}"
    normalized = normalize_supplier_offers(
        offers, requested_quantity=requested_quantity,
        available_now=available_now, deadline_days=deadline_days,
    )
    selection_id = "fs-" + hashlib.sha256(
        f"{tenant_id}|{case_id}|{expected_revision + 1}|{idempotency_key}".encode()
    ).hexdigest()[:24]
    stamp = datetime.now(timezone.utc)
    row = ShoppingCaseFulfillmentSelection(
        selection_id=selection_id, tenant_id=tenant_id, case_id=case_id, uid=uid,
        revision=expected_revision + 1, status="selected", choice=choice,
        preferred_sku=preferred_sku, requested_quantity=requested_quantity,
        available_now=available_now,
        offers_json=[item.model_dump(mode="json") for item in normalized],
        selection_idempotency_key=idempotency_key,
        created_at=stamp, updated_at=stamp,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _decode(row), None


def resolve_confirmed_cart_target(
    selection: FulfillmentSelection, *, selected_offer_id: str | None,
    substitution_authorized: bool,
) -> tuple[str, int, BuyerSafeSupplierOffer | None]:
    offer = next((row for row in selection.offers if row.offer_id == selected_offer_id), None)
    if selected_offer_id and offer is None:
        raise ValueError("supplier_offer_not_found")
    requires_offer = selection.choice in {"supplier_enquiry", "substitute"}
    if requires_offer and offer is None:
        raise ValueError("supplier_offer_selection_required")
    target = offer.offered_sku if offer else selection.preferred_sku
    is_substitution = target != selection.preferred_sku
    if is_substitution and (offer is None or offer.relationship != "compatible_substitute"):
        raise ValueError("unverified_substitution")
    if is_substitution and not substitution_authorized:
        raise ValueError("substitution_requires_explicit_authorization")
    if is_substitution and offer and offer.quantity_available < selection.requested_quantity:
        raise ValueError("substitute_quantity_insufficient")
    if selection.choice == "next_best_now" and not is_substitution:
        raise ValueError("next_best_requires_explicit_alternative_offer")
    return target, selection.requested_quantity, offer


def record_cart_confirmation(
    db, *, tenant_id: str, case_id: str, selection_id: str, uid: str,
    expected_revision: int, idempotency_key: str, selected_offer_id: str | None,
    cart_plan_id: str, cart_result: dict[str, Any],
) -> tuple[FulfillmentSelection | None, str | None]:
    row = db.execute(select(ShoppingCaseFulfillmentSelection).where(
        ShoppingCaseFulfillmentSelection.tenant_id == tenant_id,
        ShoppingCaseFulfillmentSelection.case_id == case_id,
        ShoppingCaseFulfillmentSelection.selection_id == selection_id,
        ShoppingCaseFulfillmentSelection.uid == uid,
    )).scalar_one_or_none()
    if row is None:
        return None, "fulfillment_selection_not_found"
    current = _decode(row)
    if row.confirmation_idempotency_key == idempotency_key and current.cart_result:
        return current, None
    if current.status == "cart_applied":
        return None, "fulfillment_selection_already_confirmed"
    if current.revision != expected_revision:
        return None, f"stale_fulfillment_revision:{current.revision}"
    next_revision = current.revision + 1
    changed = db.execute(update(ShoppingCaseFulfillmentSelection).where(
        ShoppingCaseFulfillmentSelection.tenant_id == tenant_id,
        ShoppingCaseFulfillmentSelection.case_id == case_id,
        ShoppingCaseFulfillmentSelection.selection_id == selection_id,
        ShoppingCaseFulfillmentSelection.revision == expected_revision,
        ShoppingCaseFulfillmentSelection.status == "selected",
    ).values(
        revision=next_revision, status="cart_applied", selected_offer_id=selected_offer_id,
        confirmation_idempotency_key=idempotency_key, cart_plan_id=cart_plan_id,
        cart_result_json=dict(cart_result), updated_at=datetime.now(timezone.utc),
    ))
    if int(getattr(changed, "rowcount", 0) or 0) != 1:
        db.rollback()
        return None, "fulfillment_confirmation_conflict"
    db.commit()
    updated = db.execute(select(ShoppingCaseFulfillmentSelection).where(
        ShoppingCaseFulfillmentSelection.selection_id == selection_id,
    )).scalar_one()
    return _decode(updated), None


__all__ = [
    "BuyerSafeSupplierOffer", "FulfillmentSelection", "SupplierOfferInput",
    "certification_fixture_offers", "normalize_supplier_offers",
    "get_confirmation_replay", "get_fulfillment_selection", "record_cart_confirmation",
    "resolve_confirmed_cart_target", "select_fulfillment_option",
]
