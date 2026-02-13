import os
from typing import Dict, Any


class BaseShippingProvider:
    name = "base-shipping"

    def create_label(self, shipment_info: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError()


class EasyPostProvider(BaseShippingProvider):
    name = "easypost"

    def __init__(self):
        self.api_key = os.getenv("EASYPOST_API_KEY")

    def create_label(self, shipment_info: Dict[str, Any]) -> Dict[str, Any]:
        if not self.api_key:
            return {"ok": True, "dev": True, "label_url": "https://example.com/dev-label.pdf"}
        try:
            import requests
            headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
            resp = requests.post(os.getenv("EASYPOST_API_URL", "https://api.easypost.com/v2/shipments"), json=shipment_info, headers=headers, timeout=10)
            try:
                j = resp.json()
            except Exception:
                j = {"status_code": resp.status_code, "text": resp.text}
            return {"ok": resp.status_code < 300, "raw": j}
        except Exception as e:
            return {"ok": False, "error": str(e)}


class ShipStationProvider(BaseShippingProvider):
    name = "shipstation"

    def __init__(self):
        self.key = os.getenv("SHIPSTATION_API_KEY")
        self.secret = os.getenv("SHIPSTATION_API_SECRET")

    def create_label(self, shipment_info: Dict[str, Any]) -> Dict[str, Any]:
        if not (self.key and self.secret):
            return {"ok": True, "dev": True, "label_url": "https://example.com/dev-label-shipstation.pdf"}
        try:
            import requests
            url = os.getenv("SHIPSTATION_API_URL", "https://ssapi.shipstation.com/shipments/createLabel")
            resp = requests.post(url, json=shipment_info, auth=(self.key, self.secret), timeout=10)
            try:
                j = resp.json()
            except Exception:
                j = {"status_code": resp.status_code, "text": resp.text}
            return {"ok": resp.status_code < 300, "raw": j}
        except Exception as e:
            return {"ok": False, "error": str(e)}


def get_default_shipping_provider():
    ep = EasyPostProvider()
    if ep.api_key:
        return ep
    ss = ShipStationProvider()
    if ss.key and ss.secret:
        return ss
    return ep
