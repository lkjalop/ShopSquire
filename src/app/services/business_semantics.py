"""Versioned canonical contracts for authoritative business observations."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.app.services.currency_authority import normalize_currency


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1


class Quantity(Contract):
    value: Decimal = Field(ge=0)
    uom: str = Field(min_length=1)

    @field_validator("uom")
    @classmethod
    def normalize_uom(cls, value: str) -> str:
        return value.strip().upper()


class Money(Contract):
    amount_minor: int
    currency: str

    @field_validator("currency")
    @classmethod
    def iso_currency(cls, value: str) -> str:
        return normalize_currency(value)


class OrderPayload(Contract):
    kind: Literal["order"] = "order"
    party_external_id: str
    status: str
    total: Money


class OrderLinePayload(Contract):
    kind: Literal["order_line"] = "order_line"
    order_external_id: str
    variant_id: str
    location_id: str | None = None
    quantity: Quantity
    unit_price: Money


class LocationATPPayload(Contract):
    kind: Literal["location_atp"] = "location_atp"
    variant_id: str
    location_id: str
    source_atp: Quantity | None = None
    on_hand: Quantity | None = None
    committed: Quantity | None = None
    incoming: Quantity | None = None
    safety_stock: Quantity | None = None
    source_basis: list[str] = Field(default_factory=list)
    source_calculated_at: str
    ttl_seconds: int = Field(default=900, ge=1, le=604800)

    @model_validator(mode="after")
    def coherent_units(self) -> "LocationATPPayload":
        units = {
            item.uom
            for item in (
                self.source_atp,
                self.on_hand,
                self.committed,
                self.incoming,
                self.safety_stock,
            )
            if item is not None
        }
        if len(units) > 1:
            raise ValueError("atp_uom_mismatch")
        if self.source_atp is None and (self.on_hand is None or self.committed is None):
            raise ValueError("source_atp_or_complete_derivation_required")
        return self


class ReservationPayload(Contract):
    kind: Literal["reservation"] = "reservation"
    variant_id: str
    location_id: str
    quantity: Quantity
    status: Literal["held", "consumed", "released", "expired"]
    expires_at: str | None = None
    idempotency_key: str


class ReturnPayload(Contract):
    kind: Literal["return"] = "return"
    order_external_id: str
    variant_id: str
    location_id: str | None = None
    quantity: Quantity
    physical_disposition: Literal["restock", "quarantine", "repair", "scrap", "return_to_vendor"]
    financial_disposition: Literal["none", "credit_pending", "credited", "refunded"]


class ReceiptPayload(Contract):
    kind: Literal["receipt"] = "receipt"
    purchase_order_external_id: str
    variant_id: str
    location_id: str
    quantity: Quantity
    custody_status: Literal["arrived", "quarantined", "accepted", "rejected", "put_away"]
    ownership_status: Literal["owned", "consigned", "unknown"]
    unit_cost: Money | None = None


class InvoicePayload(Contract):
    kind: Literal["invoice"] = "invoice"
    party_external_id: str
    status: str
    total: Money


class InvoiceLinePayload(Contract):
    kind: Literal["invoice_line"] = "invoice_line"
    invoice_external_id: str
    purchase_order_external_id: str
    receipt_external_ids: list[str] = Field(default_factory=list)
    variant_id: str
    quantity: Quantity
    unit_cost: Money


class PurchaseOrderPayload(Contract):
    kind: Literal["purchase_order"] = "purchase_order"
    supplier_external_id: str
    status: str
    total: Money


class InventoryValuationPayload(Contract):
    kind: Literal["inventory_valuation"] = "inventory_valuation"
    variant_id: str
    location_id: str
    quantity: Quantity
    value: Money
    costing_method: Literal["standard", "fifo", "avco", "specific"]
    layer_ref: str


class LandedCostPayload(Contract):
    kind: Literal["landed_cost"] = "landed_cost"
    applies_to: list[str] = Field(min_length=1)
    cost: Money
    allocation_method: Literal["equal", "quantity", "current_cost", "weight", "volume", "manual"]


class TransferPayload(Contract):
    kind: Literal["transfer"] = "transfer"
    variant_id: str
    from_location_id: str
    to_location_id: str
    quantity: Quantity
    status: Literal["planned", "in_transit", "received", "cancelled"]

    @model_validator(mode="after")
    def distinct_locations(self) -> "TransferPayload":
        if self.from_location_id == self.to_location_id:
            raise ValueError("transfer_locations_must_differ")
        return self


class InspectionPayload(Contract):
    kind: Literal["inspection"] = "inspection"
    receipt_external_id: str
    variant_id: str
    location_id: str | None = None
    quantity: Quantity
    outcome: Literal["accepted", "quarantined", "rejected"]
    reason_code: str | None = None


class InventoryAdjustmentPayload(Contract):
    kind: Literal["inventory_adjustment"] = "inventory_adjustment"
    variant_id: str
    location_id: str
    quantity_delta: Decimal
    uom: str
    reason_code: str
    approved_by: str | None = None


class MarkdownPayload(Contract):
    kind: Literal["markdown"] = "markdown"
    variant_id: str
    location_id: str
    original_price: Money
    new_price: Money
    reason_code: str
    effective_at: str
    approved_by: str

    @model_validator(mode="after")
    def coherent_price(self) -> "MarkdownPayload":
        if self.original_price.currency != self.new_price.currency:
            raise ValueError("markdown_currency_mismatch")
        if self.new_price.amount_minor > self.original_price.amount_minor:
            raise ValueError("markdown_must_not_increase_price")
        return self


class DisposalPayload(Contract):
    kind: Literal["disposal"] = "disposal"
    variant_id: str
    location_id: str
    quantity: Quantity
    custody_from: Literal["available", "quarantined", "inspection", "repair"] = "available"
    reason_code: str
    writeoff: Money | None = None
    approved_by: str


class ProcurementReconciliationPayload(Contract):
    kind: Literal["procurement_reconciliation"] = "procurement_reconciliation"
    purchase_order_external_id: str
    invoice_external_id: str
    receipt_external_ids: list[str] = Field(min_length=1)
    variant_id: str
    ordered_quantity: Quantity
    received_quantity: Quantity
    invoiced_quantity: Quantity
    quantity_tolerance: Decimal = Field(ge=0)
    ordered_unit_cost: Money
    invoiced_unit_cost: Money
    status: Literal["matched", "within_tolerance", "exception"]
    exception_reasons: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def comparable_dimensions(self) -> "ProcurementReconciliationPayload":
        units = {
            self.ordered_quantity.uom,
            self.received_quantity.uom,
            self.invoiced_quantity.uom,
        }
        if len(units) != 1:
            raise ValueError("reconciliation_uom_mismatch")
        if self.ordered_unit_cost.currency != self.invoiced_unit_cost.currency:
            raise ValueError("reconciliation_currency_mismatch")
        if self.status == "exception" and not self.exception_reasons:
            raise ValueError("reconciliation_exception_reason_required")
        return self


CanonicalPayload = Annotated[
    Union[
        OrderPayload,
        OrderLinePayload,
        LocationATPPayload,
        ReservationPayload,
        ReturnPayload,
        ReceiptPayload,
        InvoicePayload,
        InvoiceLinePayload,
        PurchaseOrderPayload,
        InventoryValuationPayload,
        LandedCostPayload,
        TransferPayload,
        InspectionPayload,
        InventoryAdjustmentPayload,
        MarkdownPayload,
        DisposalPayload,
        ProcurementReconciliationPayload,
    ],
    Field(discriminator="kind"),
]

PAYLOAD_MODELS = {
    model.model_fields["kind"].default: model
    for model in (
        OrderPayload,
        OrderLinePayload,
        LocationATPPayload,
        ReservationPayload,
        ReturnPayload,
        ReceiptPayload,
        InvoicePayload,
        InvoiceLinePayload,
        PurchaseOrderPayload,
        InventoryValuationPayload,
        LandedCostPayload,
        TransferPayload,
        InspectionPayload,
        InventoryAdjustmentPayload,
        MarkdownPayload,
        DisposalPayload,
        ProcurementReconciliationPayload,
    )
}


def validate_payload(entity_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    entity = str(entity_type or "").strip().lower()
    model = PAYLOAD_MODELS.get(entity)
    if model is None:
        raise ValueError(f"unsupported_entity_type:{entity}")
    candidate = dict(payload or {})
    candidate.setdefault("kind", entity)
    validated = model.model_validate(candidate)
    return validated.model_dump(mode="json")


def project_atp(payload: LocationATPPayload, *, now: datetime | None = None) -> dict[str, Any]:
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    calculated = datetime.fromisoformat(payload.source_calculated_at.replace("Z", "+00:00"))
    if calculated.tzinfo is None:
        calculated = calculated.replace(tzinfo=timezone.utc)
    age = (current - calculated.astimezone(timezone.utc)).total_seconds()
    stale = age < -300 or age > payload.ttl_seconds
    if payload.source_atp is not None:
        value = payload.source_atp.value
        uom = payload.source_atp.uom
        basis = "source_atp"
        completeness = "source_supplied"
    elif payload.on_hand is not None and payload.committed is not None:
        incoming = payload.incoming.value if payload.incoming else Decimal(0)
        safety = payload.safety_stock.value if payload.safety_stock else Decimal(0)
        value = max(Decimal(0), payload.on_hand.value - payload.committed.value + incoming - safety)
        uom = payload.on_hand.uom
        basis = "normalized_projection"
        completeness = "complete"
    else:  # guarded by the contract; retained as fail-closed defence
        value, uom, basis, completeness = None, None, "unavailable", "incomplete"
    return {
        "status": "stale" if stale else ("available" if value is not None else "unknown"),
        "completeness": completeness,
        "basis": basis,
        "quantity": str(value) if value is not None else None,
        "uom": uom,
        "age_seconds": max(0, round(age)),
        "authorizes_execution": bool(value is not None and not stale and completeness != "incomplete"),
    }


def convert_quantity(value: Decimal, *, factor_to_base: Decimal) -> Decimal:
    factor = Decimal(factor_to_base)
    if factor <= 0:
        raise ValueError("uom_conversion_factor_must_be_positive")
    return Decimal(value) * factor
