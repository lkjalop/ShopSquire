from __future__ import annotations

from src.app.erp.connectors.http_inventory import HTTPInventoryConnector


def create_connector() -> HTTPInventoryConnector:
    return HTTPInventoryConnector(provider_id="dynamics", env_prefix="DYNAMICS")
