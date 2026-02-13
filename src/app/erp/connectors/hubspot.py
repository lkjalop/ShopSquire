from __future__ import annotations

from src.app.erp.connectors.provider_sync import DeepProviderConnector


def create_connector() -> DeepProviderConnector:
    return DeepProviderConnector(provider="hubspot", env_prefix="HUBSPOT", outbound_map={'contact': '/contacts/upsert', 'company': '/companies/upsert', 'deal': '/deals/upsert'})
