from __future__ import annotations

from src.app.erp.connectors.provider_sync import DeepProviderConnector


def create_connector() -> DeepProviderConnector:
    return DeepProviderConnector(provider="sap", env_prefix="SAP", outbound_map={'customer': '/business-partners/upsert', 'sales_order': '/sales-orders/upsert', 'supplier': '/suppliers/upsert'})
