from __future__ import annotations

from src.app.erp.connectors.provider_sync import DeepProviderConnector


def create_connector() -> DeepProviderConnector:
    return DeepProviderConnector(provider="coupa", env_prefix="COUPA", outbound_map={'supplier': '/suppliers/upsert', 'purchase_order': '/purchase-orders/upsert', 'invoice': '/invoices/upsert'})
