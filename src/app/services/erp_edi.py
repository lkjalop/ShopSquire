from __future__ import annotations

import os
import json
from typing import Dict, Any


class ERPEDIConnector:
    """ERP/EDI connector stub with configurable mock response."""

    def __init__(self) -> None:
        self.enabled = os.getenv("ERP_EDI_ENABLED", "0").lower() in ("1", "true", "yes")
        self.base_url = os.getenv("ERP_EDI_BASE_URL", "").strip()
        self.mock_mode = os.getenv("ERP_EDI_MOCK_MODE", "1").lower() in ("1", "true", "yes")

    def get_supplier_signals(self, order_id: str) -> Dict[str, Any]:
        if not self.enabled:
            return {}
        if self.mock_mode:
            stub = self._load_stub()
            if isinstance(stub, dict):
                by_order = stub.get("orders", {}).get(order_id)
                if isinstance(by_order, dict):
                    return {"order_id": order_id, **by_order}
            return {
                "supplier_verified": True,
                "edi_status": "ok",
                "restock_eta_days": 5,
                "backorder": False,
                "invoice_verified": True,
                "order_id": order_id,
            }
        # Placeholder for real integration
        # In production, perform authenticated request to ERP/EDI system.
        return {
            "supplier_verified": None,
            "edi_status": "unknown",
            "restock_eta_days": None,
            "backorder": None,
            "invoice_verified": None,
            "order_id": order_id,
        }

    def _load_stub(self) -> Dict[str, Any]:
        path = os.getenv("ERP_EDI_STUB_PATH", os.path.join("config", "erp_edi_stub.json"))
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
