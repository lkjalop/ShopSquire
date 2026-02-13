from __future__ import annotations

from src.app.erp.connectors.provider_sync import DeepProviderConnector


def create_connector() -> DeepProviderConnector:
    return DeepProviderConnector(provider="salesforce", env_prefix="SALESFORCE", outbound_map={'lead': '/leads/upsert', 'account': '/accounts/upsert', 'opportunity': '/opportunities/upsert'})
