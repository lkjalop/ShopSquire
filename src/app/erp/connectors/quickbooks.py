from __future__ import annotations

from src.app.erp.connectors.provider_sync import DeepProviderConnector


def create_connector() -> DeepProviderConnector:
    return DeepProviderConnector(provider="quickbooks", env_prefix="QUICKBOOKS", outbound_map={'customer': '/customers/upsert', 'sales_order': '/salesreceipts/upsert', 'invoice': '/invoices/upsert'})
