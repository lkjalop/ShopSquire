from __future__ import annotations

from src.app.erp.connectors.netsuite import NetSuiteConnector


def create_connector() -> NetSuiteConnector:
    return NetSuiteConnector()
