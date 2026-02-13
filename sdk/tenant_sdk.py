"""Minimal Tenant SDK for integrating external ecommerce platforms.

Provides a base connector with common operations and webhook registration helpers.
"""
from typing import Dict, Any, Optional
import requests


class BaseTenantConnector:
    def __init__(self, api_base: str, api_key: Optional[str] = None):
        self.api_base = api_base.rstrip("/")
        self.api_key = api_key

    def _headers(self) -> Dict[str, str]:
        h = {"content-type": "application/json"}
        if self.api_key:
            h["x-api-key"] = self.api_key
        return h

    def register_webhooks(self, callback_url: str) -> Dict[str, Any]:
        payload = {"callback_url": callback_url, "events": ["order.created", "order.updated", "cart.updated"]}
        resp = requests.post(f"{self.api_base}/connectors/test", json=payload, headers=self._headers(), timeout=5)
        return {"status": resp.status_code, "response": self._safe_json(resp)}

    def push_security_event(self, path: str, details: Dict[str, Any], severity: str = "info") -> Dict[str, Any]:
        payload = {"path": path, "severity": severity, "details": details}
        resp = requests.post(f"{self.api_base}/api/v1/admin/security/events", json=payload, headers=self._headers(), timeout=5)
        return {"status": resp.status_code, "response": self._safe_json(resp)}

    def push_decision_log(self, decision: Dict[str, Any]) -> Dict[str, Any]:
        # For future direct decision ingestion; current platform writes via internal APIs
        resp = requests.post(f"{self.api_base}/api/v1/admin/compliance/evidence", json={"decision": decision}, headers=self._headers(), timeout=5)
        return {"status": resp.status_code, "response": self._safe_json(resp)}

    def _safe_json(self, resp: requests.Response) -> Any:
        try:
            return resp.json()
        except Exception:
            return {"text": resp.text}
