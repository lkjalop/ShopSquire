from __future__ import annotations

from typing import Any


PROVIDERS = {
    "netsuite": {"type": "deep", "module": "src.app.erp.connectors.netsuite_inventory", "factory": "create_connector"},
    "sap": {"type": "deep", "module": "src.app.erp.connectors.sap", "factory": "create_connector"},
    "dynamics": {"type": "deep", "module": "src.app.erp.connectors.dynamics", "factory": "create_connector"},
    "quickbooks": {"type": "deep", "module": "src.app.erp.connectors.quickbooks", "factory": "create_connector"},
    "coupa": {"type": "deep", "module": "src.app.erp.connectors.coupa", "factory": "create_connector"},
    "ariba": {"type": "deep", "module": "src.app.erp.connectors.ariba", "factory": "create_connector"},
    "salesforce": {"type": "deep", "module": "src.app.erp.connectors.salesforce", "factory": "create_connector"},
    "hubspot": {"type": "deep", "module": "src.app.erp.connectors.hubspot", "factory": "create_connector"},
}


def load_provider(provider: str):
    p = str(provider or "").strip().lower()
    if p not in PROVIDERS:
        raise ValueError("unsupported_provider")
    entry = PROVIDERS[p]
    mod = __import__(entry["module"], fromlist=[entry["factory"]])
    fn = getattr(mod, entry["factory"])
    return fn()

