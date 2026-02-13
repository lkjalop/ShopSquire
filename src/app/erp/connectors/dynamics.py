from __future__ import annotations

from src.app.erp.connectors.provider_sync import DeepProviderConnector


def create_connector() -> DeepProviderConnector:
    return DeepProviderConnector(provider="dynamics", env_prefix="DYNAMICS", outbound_map={'customer': '/contacts/upsert', 'sales_order': '/sales-orders/upsert', 'invoice': '/invoices/upsert'})
