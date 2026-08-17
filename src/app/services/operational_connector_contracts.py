"""Vendor-neutral contracts for governed operational connector deliveries.

The contract deliberately separates enrollment from delivered facts.  A
payload cannot make itself an enrolled WMS, retailer, supplier, or carrier and
credentials are referenced by secret identifier rather than carried in data.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.app.services.shopping_case_operational_observations import (
    OperationalObservationInput,
)
from src.app.services.tool_capability_selector import ToolCapability


class ConnectorKind(StrEnum):
    WMS = "wms"
    RETAILER_PRICE = "retailer_price"
    SUPPLIER = "supplier"
    CARRIER = "carrier"


_CAPABILITY = {
    ConnectorKind.WMS: ToolCapability.INVENTORY_AVAILABILITY,
    ConnectorKind.RETAILER_PRICE: ToolCapability.FORECAST_OBSERVATION_READ,
    ConnectorKind.SUPPLIER: ToolCapability.SUPPLIER_OFFER_READ,
    ConnectorKind.CARRIER: ToolCapability.CARRIER_SERVICE_READ,
}


class OperationalConnectorEnrollment(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    connector_id: str = Field(min_length=3, max_length=120)
    tenant_id: str = Field(min_length=1, max_length=200)
    kind: ConnectorKind
    capability: ToolCapability
    endpoint_origin: str = Field(min_length=1, max_length=500)
    auth_mode: Literal["api_key", "oauth2", "mtls", "signed_webhook", "none"]
    credential_ref: str | None = Field(default=None, max_length=240)
    allowed_schema_versions: tuple[str, ...] = Field(min_length=1, max_length=8)
    freshness_sla_seconds: int = Field(ge=30, le=2_592_000)
    execution_mode: Literal["live_network", "certification_fixture"]
    enabled: bool = False

    @model_validator(mode="after")
    def validate_enrollment(self) -> "OperationalConnectorEnrollment":
        if self.capability != _CAPABILITY[self.kind]:
            raise ValueError("connector_capability_kind_mismatch")
        parsed = urlparse(self.endpoint_origin)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("connector_endpoint_origin_invalid")
        if self.execution_mode == "live_network":
            if parsed.scheme != "https":
                raise ValueError("live_connector_requires_https")
            if self.auth_mode == "none" or not self.credential_ref:
                raise ValueError("live_connector_requires_authentication")
        if self.credential_ref and not self.credential_ref.startswith(
            ("secret://", "env://", "vault://")
        ):
            raise ValueError("connector_credential_must_be_a_secret_reference")
        return self


class ConnectorFact(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    fact_id: str = Field(min_length=8, max_length=160)
    subject_ref: str = Field(min_length=1, max_length=200)
    location_ref: str | None = Field(default=None, max_length=200)
    effective_at: str
    data: dict[str, Any]


class ConnectorDelivery(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    delivery_id: str = Field(min_length=8, max_length=160)
    connector_id: str = Field(min_length=3, max_length=120)
    tenant_id: str = Field(min_length=1, max_length=200)
    source_schema_version: str = Field(min_length=1, max_length=80)
    watermark_before: str | None = Field(default=None, max_length=240)
    watermark_after: str = Field(min_length=1, max_length=240)
    observed_at: str
    facts: tuple[ConnectorFact, ...] = Field(min_length=1, max_length=100)


class ConnectorNormalizationReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["operational-connector-receipt-v1"] = (
        "operational-connector-receipt-v1"
    )
    connector_id: str
    connector_kind: ConnectorKind
    execution_mode: Literal["live_network", "certification_fixture"]
    source_schema_version: str
    delivery_id: str
    normalized_count: int
    rejected_count: int
    watermark_before: str | None
    watermark_after: str
    external_calls: int
    paid_calls: Literal[0] = 0
    commercial_authority_granted: Literal[False] = False


def _utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("connector_time_requires_timezone")
    return parsed.astimezone(timezone.utc)


def _source_type(kind: ConnectorKind) -> str:
    return {
        ConnectorKind.WMS: "inventory_system",
        ConnectorKind.RETAILER_PRICE: "price_feed",
        ConnectorKind.SUPPLIER: "supplier",
        ConnectorKind.CARRIER: "carrier_system",
    }[kind]


def _observation_kind(kind: ConnectorKind, data: dict[str, Any]) -> str:
    if kind == ConnectorKind.WMS:
        return "inventory_quantity"
    if kind == ConnectorKind.RETAILER_PRICE:
        return "price"
    if kind == ConnectorKind.CARRIER:
        return "carrier_calendar"
    supplier_fact = str(data.get("fact_type") or "").strip()
    mapping = {
        "response": "supplier_response",
        "lead_time": "supplier_lead_time",
        "quote_validity": "quote_validity",
    }
    if supplier_fact not in mapping:
        raise ValueError("supplier_fact_type_unsupported")
    return mapping[supplier_fact]


def normalize_connector_delivery(
    enrollment: OperationalConnectorEnrollment,
    delivery: ConnectorDelivery,
    *,
    expected_revision: int,
) -> tuple[list[OperationalObservationInput], ConnectorNormalizationReceipt]:
    """Normalize an enrolled delivery without performing any commercial action."""

    if not enrollment.enabled:
        raise ValueError("connector_not_enabled")
    if delivery.connector_id != enrollment.connector_id:
        raise ValueError("connector_identity_mismatch")
    if delivery.tenant_id != enrollment.tenant_id:
        raise ValueError("connector_tenant_mismatch")
    if delivery.source_schema_version not in enrollment.allowed_schema_versions:
        raise ValueError("connector_schema_version_not_allowed")
    observed = _utc(delivery.observed_at)
    if delivery.watermark_before == delivery.watermark_after:
        raise ValueError("connector_watermark_did_not_advance")

    normalized: list[OperationalObservationInput] = []
    rejected = 0
    for fact in delivery.facts:
        try:
            effective = _utc(fact.effective_at)
            data = dict(fact.data)
            data.pop("fact_type", None)
            normalized.append(OperationalObservationInput(
                observation_id=fact.fact_id,
                expected_revision=expected_revision + len(normalized),
                kind=_observation_kind(enrollment.kind, fact.data),
                subject_ref=fact.subject_ref,
                location_ref=fact.location_ref,
                value=data,
                source_type=_source_type(enrollment.kind),
                evidence_ref=(
                    f"connector:{enrollment.connector_id}:delivery:{delivery.delivery_id}"
                ),
                known_at=observed.isoformat(),
                effective_at=effective.isoformat(),
            ))
        except (TypeError, ValueError):
            rejected += 1
    receipt = ConnectorNormalizationReceipt(
        connector_id=enrollment.connector_id,
        connector_kind=enrollment.kind,
        execution_mode=enrollment.execution_mode,
        source_schema_version=delivery.source_schema_version,
        delivery_id=delivery.delivery_id,
        normalized_count=len(normalized),
        rejected_count=rejected,
        watermark_before=delivery.watermark_before,
        watermark_after=delivery.watermark_after,
        external_calls=1 if enrollment.execution_mode == "live_network" else 0,
    )
    return normalized, receipt


__all__ = [
    "ConnectorDelivery", "ConnectorFact", "ConnectorKind",
    "ConnectorNormalizationReceipt", "OperationalConnectorEnrollment",
    "normalize_connector_delivery",
]
