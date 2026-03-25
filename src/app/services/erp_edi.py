from __future__ import annotations

import logging
import os
import json
from typing import Any, Dict, List, Optional
from src.app.services.edi_parser import parse_edi_document

_log = logging.getLogger(__name__)


class ERPEDIConnector:
    """ERP/EDI connector with optional mock mode and native EDI parser."""

    def __init__(self) -> None:
        self.enabled = os.getenv("ERP_EDI_ENABLED", "0").lower() in ("1", "true", "yes")
        self.base_url = os.getenv("ERP_EDI_BASE_URL", "").strip()
        self.mock_mode = os.getenv("ERP_EDI_MOCK_MODE", "0").lower() in ("1", "true", "yes")
        self.connector_type = os.getenv("ERP_CONNECTOR_TYPE", "mock").lower()

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
        # Delegate to real connector
        return self._real_get_supplier_signals(order_id)

    def _real_get_supplier_signals(self, order_id: str) -> Dict[str, Any]:
        """Route to the configured real ERP connector."""
        connector = _get_real_connector(self.connector_type, self.base_url)
        if connector:
            return connector.get_order(order_id)
        return {
            "supplier_verified": None,
            "edi_status": "unknown",
            "restock_eta_days": None,
            "backorder": None,
            "invoice_verified": None,
            "order_id": order_id,
        }

    def submit_order(self, order_data: Dict[str, Any]) -> Dict[str, Any]:
        """Submit an order to the ERP system."""
        if not self.enabled:
            return {"status": "disabled"}
        if self.mock_mode:
            return {"status": "mock_accepted", "order_id": order_data.get("order_id", "mock-001")}
        connector = _get_real_connector(self.connector_type, self.base_url)
        if connector:
            return connector.submit_order(order_data)
        return {"status": "no_connector"}

    def get_inventory(self, sku: str) -> Dict[str, Any]:
        """Query real-time inventory from ERP."""
        if not self.enabled:
            return {}
        if self.mock_mode:
            return {"sku": sku, "available": 100, "reserved": 0, "source": "mock"}
        connector = _get_real_connector(self.connector_type, self.base_url)
        if connector:
            return connector.get_inventory(sku)
        return {"sku": sku, "available": None, "source": "unavailable"}

    def get_shipping_status(self, order_id: str) -> Dict[str, Any]:
        """Query shipping/fulfillment status."""
        if not self.enabled:
            return {}
        if self.mock_mode:
            return {"order_id": order_id, "status": "shipped", "tracking": "MOCK-TRACK-001", "carrier": "mock_carrier"}
        connector = _get_real_connector(self.connector_type, self.base_url)
        if connector:
            return connector.get_shipping(order_id)
        return {"order_id": order_id, "status": "unknown"}

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


# ── Real connector implementations ───────────────────────────────


class BaseERPConnector:
    """Base class for real ERP connectors."""

    def get_order(self, order_id: str) -> Dict[str, Any]:
        raise NotImplementedError

    def submit_order(self, order_data: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError

    def get_inventory(self, sku: str) -> Dict[str, Any]:
        raise NotImplementedError

    def get_shipping(self, order_id: str) -> Dict[str, Any]:
        raise NotImplementedError


class HTTPGenericConnector(BaseERPConnector):
    """Generic HTTP REST connector for any ERP with a REST API."""

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self.api_key = os.getenv("ERP_API_KEY", "")
        self.timeout = int(os.getenv("ERP_TIMEOUT_SEC", "15"))

    def _headers(self) -> Dict[str, str]:
        h: Dict[str, str] = {"Content-Type": "application/json"}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h

    def _get(self, path: str) -> Dict[str, Any]:
        import requests
        resp = requests.get(f"{self.base_url}{path}", headers=self._headers(), timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    def _post(self, path: str, data: Dict[str, Any]) -> Dict[str, Any]:
        import requests
        resp = requests.post(f"{self.base_url}{path}", json=data, headers=self._headers(), timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    def get_order(self, order_id: str) -> Dict[str, Any]:
        try:
            return self._get(f"/orders/{order_id}")
        except Exception as e:
            _log.warning("ERP HTTP get_order failed: %s", e)
            return {"order_id": order_id, "error": str(e)}

    def submit_order(self, order_data: Dict[str, Any]) -> Dict[str, Any]:
        try:
            return self._post("/orders", order_data)
        except Exception as e:
            _log.warning("ERP HTTP submit_order failed: %s", e)
            return {"status": "error", "error": str(e)}

    def get_inventory(self, sku: str) -> Dict[str, Any]:
        try:
            return self._get(f"/inventory/{sku}")
        except Exception as e:
            _log.warning("ERP HTTP get_inventory failed: %s", e)
            return {"sku": sku, "error": str(e)}

    def get_shipping(self, order_id: str) -> Dict[str, Any]:
        try:
            return self._get(f"/shipping/{order_id}")
        except Exception as e:
            _log.warning("ERP HTTP get_shipping failed: %s", e)
            return {"order_id": order_id, "error": str(e)}


class SAPBusinessOneConnector(BaseERPConnector):
    """SAP Business One Service Layer connector."""

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self.company_db = os.getenv("SAP_B1_COMPANY_DB", "")
        self.username = os.getenv("SAP_B1_USERNAME", "")
        self.password = os.getenv("SAP_B1_PASSWORD", "")
        self.session_id: str | None = None
        self.timeout = int(os.getenv("ERP_TIMEOUT_SEC", "15"))

    def _login(self) -> None:
        if self.session_id:
            return
        import requests
        resp = requests.post(
            f"{self.base_url}/Login",
            json={"CompanyDB": self.company_db, "UserName": self.username, "Password": self.password},
            timeout=self.timeout,
            verify=True,
        )
        resp.raise_for_status()
        self.session_id = resp.cookies.get("B1SESSION")

    def _get(self, path: str) -> Dict[str, Any]:
        import requests
        self._login()
        resp = requests.get(
            f"{self.base_url}{path}",
            cookies={"B1SESSION": self.session_id} if self.session_id else {},
            timeout=self.timeout,
            verify=True,
        )
        if resp.status_code == 401:
            self.session_id = None
            self._login()
            resp = requests.get(
                f"{self.base_url}{path}",
                cookies={"B1SESSION": self.session_id} if self.session_id else {},
                timeout=self.timeout,
                verify=True,
            )
        resp.raise_for_status()
        return resp.json()

    def get_order(self, order_id: str) -> Dict[str, Any]:
        try:
            data = self._get(f"/Orders('{order_id}')")
            return {
                "order_id": order_id,
                "supplier_verified": True,
                "edi_status": data.get("DocumentStatus", "unknown"),
                "total": data.get("DocTotal"),
                "currency": data.get("DocCurrency"),
                "raw": data,
            }
        except Exception as e:
            _log.warning("SAP B1 get_order failed: %s", e)
            return {"order_id": order_id, "error": str(e)}

    def submit_order(self, order_data: Dict[str, Any]) -> Dict[str, Any]:
        try:
            import requests
            self._login()
            resp = requests.post(
                f"{self.base_url}/Orders",
                json=order_data,
                cookies={"B1SESSION": self.session_id} if self.session_id else {},
                timeout=self.timeout,
                verify=True,
            )
            resp.raise_for_status()
            return {"status": "created", "data": resp.json()}
        except Exception as e:
            _log.warning("SAP B1 submit_order failed: %s", e)
            return {"status": "error", "error": str(e)}

    def get_inventory(self, sku: str) -> Dict[str, Any]:
        try:
            data = self._get(f"/Items('{sku}')")
            return {
                "sku": sku,
                "available": data.get("QuantityOnStock", 0),
                "committed": data.get("QuantityOrderedByCustomers", 0),
                "source": "sap_b1",
            }
        except Exception as e:
            _log.warning("SAP B1 get_inventory failed: %s", e)
            return {"sku": sku, "error": str(e)}

    def get_shipping(self, order_id: str) -> Dict[str, Any]:
        try:
            data = self._get(f"/DeliveryNotes?$filter=DocNum eq {order_id}")
            entries = data.get("value", [])
            if entries:
                return {"order_id": order_id, "status": "delivered", "entries": len(entries)}
            return {"order_id": order_id, "status": "pending"}
        except Exception as e:
            _log.warning("SAP B1 get_shipping failed: %s", e)
            return {"order_id": order_id, "error": str(e)}


class NetSuiteConnector(BaseERPConnector):
    """NetSuite SuiteTalk REST connector."""

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self.token_id = os.getenv("NETSUITE_TOKEN_ID", "")
        self.token_secret = os.getenv("NETSUITE_TOKEN_SECRET", "")
        self.consumer_key = os.getenv("NETSUITE_CONSUMER_KEY", "")
        self.consumer_secret = os.getenv("NETSUITE_CONSUMER_SECRET", "")
        self.account_id = os.getenv("NETSUITE_ACCOUNT_ID", "")
        self.timeout = int(os.getenv("ERP_TIMEOUT_SEC", "15"))

    def _auth_header(self) -> str:
        """Build OAuth 1.0 header for NetSuite TBA.

        Full OAuth signing requires nonce/timestamp/signature_base per RFC 5849.
        This is a simplified version — production should use requests-oauthlib.
        """
        import time
        import hashlib
        import hmac
        import base64
        import uuid

        nonce = uuid.uuid4().hex
        timestamp = str(int(time.time()))
        base_string = f"GET&{self.base_url}&oauth_consumer_key={self.consumer_key}&oauth_nonce={nonce}&oauth_timestamp={timestamp}&oauth_token={self.token_id}"
        signing_key = f"{self.consumer_secret}&{self.token_secret}".encode()
        signature = base64.b64encode(
            hmac.new(signing_key, base_string.encode(), hashlib.sha256).digest()
        ).decode()
        return (
            f'OAuth realm="{self.account_id}",'
            f'oauth_consumer_key="{self.consumer_key}",'
            f'oauth_token="{self.token_id}",'
            f'oauth_nonce="{nonce}",'
            f'oauth_timestamp="{timestamp}",'
            f'oauth_signature_method="HMAC-SHA256",'
            f'oauth_signature="{signature}",'
            f'oauth_version="1.0"'
        )

    def _get(self, path: str) -> Dict[str, Any]:
        import requests
        resp = requests.get(
            f"{self.base_url}{path}",
            headers={"Authorization": self._auth_header(), "Content-Type": "application/json"},
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()

    def get_order(self, order_id: str) -> Dict[str, Any]:
        try:
            data = self._get(f"/record/v1/salesOrder/{order_id}")
            return {
                "order_id": order_id,
                "supplier_verified": True,
                "edi_status": data.get("status", {}).get("refName", "unknown"),
                "total": data.get("total"),
                "raw": data,
            }
        except Exception as e:
            _log.warning("NetSuite get_order failed: %s", e)
            return {"order_id": order_id, "error": str(e)}

    def submit_order(self, order_data: Dict[str, Any]) -> Dict[str, Any]:
        try:
            import requests
            resp = requests.post(
                f"{self.base_url}/record/v1/salesOrder",
                json=order_data,
                headers={"Authorization": self._auth_header(), "Content-Type": "application/json"},
                timeout=self.timeout,
            )
            resp.raise_for_status()
            return {"status": "created", "data": resp.json()}
        except Exception as e:
            _log.warning("NetSuite submit_order failed: %s", e)
            return {"status": "error", "error": str(e)}

    def get_inventory(self, sku: str) -> Dict[str, Any]:
        try:
            data = self._get(f"/record/v1/inventoryItem?q=itemId IS {sku}")
            items = data.get("items", [])
            if items:
                return {
                    "sku": sku,
                    "available": items[0].get("quantityAvailable", 0),
                    "on_hand": items[0].get("quantityOnHand", 0),
                    "source": "netsuite",
                }
            return {"sku": sku, "available": 0, "source": "netsuite"}
        except Exception as e:
            _log.warning("NetSuite get_inventory failed: %s", e)
            return {"sku": sku, "error": str(e)}

    def get_shipping(self, order_id: str) -> Dict[str, Any]:
        try:
            data = self._get(f"/record/v1/itemFulfillment?q=createdFrom IS {order_id}")
            items = data.get("items", [])
            if items:
                return {"order_id": order_id, "status": "fulfilled", "fulfillments": len(items)}
            return {"order_id": order_id, "status": "pending"}
        except Exception as e:
            _log.warning("NetSuite get_shipping failed: %s", e)
            return {"order_id": order_id, "error": str(e)}


# ── Connector factory ──

_CONNECTOR_CACHE: Dict[str, BaseERPConnector] = {}


def _get_real_connector(connector_type: str, base_url: str) -> Optional[BaseERPConnector]:
    """Factory: return the correct real ERP connector based on config."""
    cache_key = f"{connector_type}:{base_url}"
    if cache_key in _CONNECTOR_CACHE:
        return _CONNECTOR_CACHE[cache_key]

    connector: Optional[BaseERPConnector] = None
    if connector_type == "http" and base_url:
        connector = HTTPGenericConnector(base_url)
    elif connector_type == "sap_b1" and base_url:
        connector = SAPBusinessOneConnector(base_url)
    elif connector_type == "netsuite" and base_url:
        connector = NetSuiteConnector(base_url)
    else:
        _log.warning("Unknown ERP connector type: %s", connector_type)
        return None

    _CONNECTOR_CACHE[cache_key] = connector
    return connector
