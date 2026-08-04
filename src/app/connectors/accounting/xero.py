from __future__ import annotations

import os
from typing import Any, Dict

import httpx

from src.app.security.url_guard import ensure_safe_outbound_url


class XeroConnector:
    def __init__(self) -> None:
        self.api_base = str(os.getenv("XERO_API_BASE", "https://api.xero.com") or "https://api.xero.com").rstrip("/")
        self.tenant_id = str(os.getenv("XERO_TENANT_ID", "") or "").strip()
        self.access_token = str(os.getenv("XERO_ACCESS_TOKEN", "") or "").strip()
        self.timeout_seconds = float(os.getenv("XERO_TIMEOUT_SECONDS", "10") or 10)
        ensure_safe_outbound_url(self.api_base)

    def _headers(self) -> Dict[str, str]:
        if not self.tenant_id or not self.access_token:
            raise RuntimeError("xero_not_configured")
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Xero-tenant-id": self.tenant_id,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def _post(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        url = f"{self.api_base}{path}"
        ensure_safe_outbound_url(url)
        with httpx.Client(timeout=self.timeout_seconds) as client:
            r = client.post(url, headers=self._headers(), json=payload)
            try:
                body = r.json() if r.text else {}
            except (TypeError, ValueError):
                body = {"provider_text": str(r.text or "")[:500]}
            return {"status_code": int(r.status_code), "ok": bool(200 <= r.status_code < 300), "body": body}

    def _get(self, path: str) -> Dict[str, Any]:
        url = f"{self.api_base}{path}"
        ensure_safe_outbound_url(url)
        with httpx.Client(timeout=self.timeout_seconds) as client:
            r = client.get(url, headers=self._headers())
            try:
                body = r.json() if r.text else {}
            except (TypeError, ValueError):
                body = {"provider_text": str(r.text or "")[:500]}
            return {"status_code": int(r.status_code), "ok": bool(200 <= r.status_code < 300), "body": body}

    def push_credit_note(self, decision_id: str, amount: float, reason: str) -> Dict[str, Any]:
        payload = {
            "CreditNotes": [
                {
                    "Type": "ACCRECCREDIT",
                    "Reference": str(decision_id),
                    "LineItems": [{"Description": str(reason), "Quantity": 1, "UnitAmount": float(amount)}],
                    "Status": "DRAFT",
                }
            ]
        }
        return self._post("/api.xro/2.0/CreditNotes", payload)

    def push_purchase_order(self, po_data: Dict[str, Any]) -> Dict[str, Any]:
        payload = {"PurchaseOrders": [dict(po_data or {})]}
        return self._post("/api.xro/2.0/PurchaseOrders", payload)

    def push_invoice(self, order_data: Dict[str, Any]) -> Dict[str, Any]:
        payload = {"Invoices": [dict(order_data or {})]}
        return self._post("/api.xro/2.0/Invoices", payload)

    def push_inventory_adjustment(self, sku: str, qty: int, reason: str) -> Dict[str, Any]:
        payload = {
            "Items": [
                {
                    "Code": str(sku),
                    "Description": str(reason),
                    "QuantityOnHand": int(qty),
                }
            ]
        }
        return self._post("/api.xro/2.0/Items", payload)

    def reconcile_payments(self, date_range: tuple[str, str]) -> Dict[str, Any]:
        start, end = date_range
        return self._get(f"/api.xro/2.0/Payments?where=Date%20%3E%3D%20DateTime({start})%20AND%20Date%20%3C%3D%20DateTime({end})")

