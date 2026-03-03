from __future__ import annotations

import os
import json
from typing import Dict, Any
from src.app.services.edi_parser import parse_edi_document


class ERPEDIConnector:
    """ERP/EDI connector with optional mock mode and native EDI parser."""

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
                    raw_edi = str(by_order.get("edi_raw") or "").strip()
                    parsed = parse_edi_document(raw_edi) if raw_edi else {}
                    return {"order_id": order_id, **by_order, "edi_parsed": parsed}
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

    def parse_document(self, payload: str | Dict[str, Any]) -> Dict[str, Any]:
        if isinstance(payload, dict):
            raw = str(payload.get("raw") or payload.get("edi_raw") or "")
        else:
            raw = str(payload or "")
        return parse_edi_document(raw)

    def _load_stub(self) -> Dict[str, Any]:
        path = os.getenv("ERP_EDI_STUB_PATH", os.path.join("config", "erp_edi_stub.json"))
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
