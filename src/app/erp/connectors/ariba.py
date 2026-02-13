from __future__ import annotations

from src.app.erp.connectors.provider_sync import DeepProviderConnector


def create_connector() -> DeepProviderConnector:
    return DeepProviderConnector(provider="ariba", env_prefix="ARIBA", outbound_map={'supplier': '/suppliers/upsert', 'purchase_order': '/purchase-orders/upsert', 'invoice': '/invoices/upsert'})
