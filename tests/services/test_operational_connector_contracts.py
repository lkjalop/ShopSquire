import pytest
from pydantic import ValidationError

from src.app.services.operational_connector_contracts import (
    ConnectorDelivery,
    ConnectorFact,
    OperationalConnectorEnrollment,
    normalize_connector_delivery,
)


def _enrollment(kind="wms", *, mode="certification_fixture", enabled=True):
    capabilities = {
        "wms": "inventory_availability",
        "retailer_price": "forecast_observation_read",
        "supplier": "supplier_offer_read",
        "carrier": "carrier_service_read",
    }
    return OperationalConnectorEnrollment(
        connector_id=f"fixture-{kind}", tenant_id="tenant-a", kind=kind,
        capability=capabilities[kind], endpoint_origin="http://127.0.0.1:9999",
        auth_mode="none", allowed_schema_versions=("v1",),
        freshness_sla_seconds=3600, execution_mode=mode, enabled=enabled,
    )


@pytest.mark.parametrize(("kind", "data", "expected"), [
    ("wms", {"quantity": 12, "facility_kind": "warehouse"}, "inventory_quantity"),
    ("retailer_price", {"amount_cents": 499_900, "currency": "AUD"}, "price"),
    ("supplier", {"fact_type": "lead_time", "days": 8}, "supplier_lead_time"),
    ("carrier", {"lane_id": "lane-a", "lead_time_days": 2}, "carrier_calendar"),
])
def test_fixture_connectors_normalize_to_one_case_contract(kind, data, expected):
    delivery = ConnectorDelivery(
        delivery_id=f"delivery-{kind}", connector_id=f"fixture-{kind}",
        tenant_id="tenant-a", source_schema_version="v1",
        watermark_before="10", watermark_after="11",
        observed_at="2026-08-18T00:00:00Z",
        facts=(ConnectorFact(
            fact_id=f"fact-{kind}-0001", subject_ref="configuration:CFG-1",
            location_ref="facility:a", effective_at="2026-08-18T00:00:00Z",
            data=data,
        ),),
    )
    rows, receipt = normalize_connector_delivery(
        _enrollment(kind), delivery, expected_revision=4,
    )
    assert rows[0].kind == expected
    assert rows[0].expected_revision == 4
    assert receipt.normalized_count == 1
    assert receipt.external_calls == receipt.paid_calls == 0
    assert receipt.execution_mode == "certification_fixture"
    assert receipt.commercial_authority_granted is False


def test_payload_cannot_self_enroll_or_cross_tenant():
    delivery = ConnectorDelivery(
        delivery_id="delivery-cross-tenant", connector_id="fixture-wms",
        tenant_id="tenant-b", source_schema_version="v1",
        watermark_before=None, watermark_after="1",
        observed_at="2026-08-18T00:00:00Z",
        facts=(ConnectorFact(
            fact_id="fact-cross-tenant", subject_ref="configuration:CFG-1",
            effective_at="2026-08-18T00:00:00Z", data={"quantity": 1},
        ),),
    )
    with pytest.raises(ValueError, match="connector_tenant_mismatch"):
        normalize_connector_delivery(_enrollment(), delivery, expected_revision=1)
    with pytest.raises(ValueError, match="connector_not_enabled"):
        normalize_connector_delivery(
            _enrollment(enabled=False), delivery.model_copy(update={"tenant_id": "tenant-a"}),
            expected_revision=1,
        )


def test_live_connector_requires_https_auth_and_secret_reference():
    with pytest.raises(ValidationError, match="live_connector_requires_https"):
        _enrollment(mode="live_network")
    with pytest.raises(ValidationError, match="connector_credential_must_be_a_secret_reference"):
        OperationalConnectorEnrollment(
            connector_id="live-wms", tenant_id="tenant-a", kind="wms",
            capability="inventory_availability", endpoint_origin="https://wms.example",
            auth_mode="api_key", credential_ref="raw-secret-value",
            allowed_schema_versions=("v1",), freshness_sla_seconds=300,
            execution_mode="live_network", enabled=True,
        )


def test_bad_fact_is_counted_not_promoted_to_zero_or_unknown_supply():
    delivery = ConnectorDelivery(
        delivery_id="delivery-invalid-fact", connector_id="fixture-wms",
        tenant_id="tenant-a", source_schema_version="v1",
        watermark_before="1", watermark_after="2",
        observed_at="2026-08-18T00:00:00Z",
        facts=(ConnectorFact(
            fact_id="fact-invalid-0001", subject_ref="configuration:CFG-1",
            effective_at="2026-08-18T00:00:00Z", data={},
        ),),
    )
    rows, receipt = normalize_connector_delivery(
        _enrollment(), delivery, expected_revision=1,
    )
    assert rows == []
    assert receipt.rejected_count == 1
    assert receipt.normalized_count == 0
