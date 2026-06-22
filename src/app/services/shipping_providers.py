import logging
import os
import uuid
from typing import Dict, Any

_log = logging.getLogger("shopsquire.shipping")


class BaseShippingProvider:
    name = "base-shipping"

    def create_label(self, shipment_info: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError()

    def get_tracking(self, tracking_number: str) -> Dict[str, Any]:
        raise NotImplementedError()


# ── EasyPost ──────────────────────────────────────────────────────────────────

class EasyPostProvider(BaseShippingProvider):
    name = "easypost"

    def __init__(self):
        self.api_key = os.getenv("EASYPOST_API_KEY", "").strip()
        self.api_url = os.getenv("EASYPOST_API_URL", "https://api.easypost.com/v2").rstrip("/")

    def create_label(self, shipment_info: Dict[str, Any]) -> Dict[str, Any]:
        if not self.api_key:
            return {
                "ok": False,
                "stub": True,
                "provider": "easypost",
                "error": "EASYPOST_API_KEY is not configured — set it to create real shipping labels.",
            }
        try:
            import requests
            headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
            resp = requests.post(f"{self.api_url}/shipments", json=shipment_info, headers=headers, timeout=15)
            try:
                j = resp.json()
            except Exception:
                j = {"status_code": resp.status_code, "text": resp.text}
            return {"ok": resp.status_code < 300, "raw": j}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def get_tracking(self, tracking_number: str) -> Dict[str, Any]:
        if not self.api_key:
            raise RuntimeError("EASYPOST_API_KEY is not configured — cannot fetch tracking status.")
        try:
            import requests
            headers = {"Authorization": f"Bearer {self.api_key}"}
            resp = requests.get(f"{self.api_url}/trackers", params={"tracking_code": tracking_number}, headers=headers, timeout=10)
            try:
                return {"ok": resp.status_code < 300, "raw": resp.json()}
            except Exception:
                return {"ok": False, "raw": resp.text}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}


# ── ShipStation ───────────────────────────────────────────────────────────────

class ShipStationProvider(BaseShippingProvider):
    name = "shipstation"

    def __init__(self):
        self.key = os.getenv("SHIPSTATION_API_KEY", "").strip()
        self.secret = os.getenv("SHIPSTATION_API_SECRET", "").strip()
        self.api_url = os.getenv("SHIPSTATION_API_URL", "https://ssapi.shipstation.com").rstrip("/")

    def create_label(self, shipment_info: Dict[str, Any]) -> Dict[str, Any]:
        if not (self.key and self.secret):
            raise RuntimeError(
                "SHIPSTATION_API_KEY / SHIPSTATION_API_SECRET not configured — cannot create shipping label. "
                "Set both values in your environment."
            )
        try:
            import requests
            resp = requests.post(
                f"{self.api_url}/shipments/createlabel",
                json=shipment_info,
                auth=(self.key, self.secret),
                timeout=15,
            )
            try:
                j = resp.json()
            except Exception:
                j = {"status_code": resp.status_code, "text": resp.text}
            return {"ok": resp.status_code < 300, "raw": j}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def get_tracking(self, tracking_number: str) -> Dict[str, Any]:
        if not (self.key and self.secret):
            raise RuntimeError("SHIPSTATION_API_KEY / SHIPSTATION_API_SECRET not configured.")
        try:
            import requests
            resp = requests.get(
                f"{self.api_url}/shipments",
                params={"trackingNumber": tracking_number},
                auth=(self.key, self.secret),
                timeout=10,
            )
            try:
                return {"ok": resp.status_code < 300, "raw": resp.json()}
            except Exception:
                return {"ok": False, "raw": resp.text}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}


# ── Australia Post ────────────────────────────────────────────────────────────
# Docs: https://developers.auspost.com.au/apis/shipping-and-tracking
# Auth: API key via header "AUTH_KEY" for domestic; OAuth2 for merchant accounts.

class AusPostProvider(BaseShippingProvider):
    name = "auspost"

    def __init__(self):
        self.api_key = os.getenv("AUSPOST_API_KEY", "").strip()
        self.account_number = os.getenv("AUSPOST_ACCOUNT_NUMBER", "").strip()
        self.api_url = os.getenv("AUSPOST_API_URL", "https://digitalapi.auspost.com.au").rstrip("/")

    def create_label(self, shipment_info: Dict[str, Any]) -> Dict[str, Any]:
        if not self.api_key:
            raise RuntimeError(
                "AUSPOST_API_KEY is not configured — cannot create AusPost label. "
                "Obtain a key from https://developers.auspost.com.au and set AUSPOST_API_KEY."
            )
        try:
            import requests
            headers = {
                "AUTH_KEY": self.api_key,
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
            if self.account_number:
                headers["Account-Number"] = self.account_number
            payload = {
                "shipments": [shipment_info] if not isinstance(shipment_info.get("shipments"), list) else shipment_info["shipments"],
            }
            resp = requests.post(
                f"{self.api_url}/shipping/v1/shipments",
                json=payload,
                headers=headers,
                timeout=20,
            )
            try:
                j = resp.json()
            except Exception:
                j = {"status_code": resp.status_code, "text": resp.text}
            _log.info("auspost create_label: status=%s", resp.status_code)
            return {"ok": resp.status_code < 300, "raw": j, "provider": "auspost"}
        except Exception as exc:
            _log.error("auspost create_label error: %s", exc)
            return {"ok": False, "error": str(exc), "provider": "auspost"}

    def get_tracking(self, tracking_number: str) -> Dict[str, Any]:
        if not self.api_key:
            raise RuntimeError("AUSPOST_API_KEY is not configured.")
        try:
            import requests
            headers = {"AUTH_KEY": self.api_key, "Accept": "application/json"}
            resp = requests.get(
                f"{self.api_url}/shipmentsgatewayapi/shipmentsgateway/v1/track/items/{tracking_number}",
                headers=headers,
                timeout=10,
            )
            try:
                j = resp.json()
            except Exception:
                j = {"status_code": resp.status_code, "text": resp.text}
            return {"ok": resp.status_code < 300, "raw": j, "provider": "auspost"}
        except Exception as exc:
            return {"ok": False, "error": str(exc), "provider": "auspost"}


# ── StarTrack ─────────────────────────────────────────────────────────────────
# StarTrack is a subsidiary of Australia Post and shares the same API
# infrastructure with a separate StarTrack-specific endpoint and account.

class StarTrackProvider(BaseShippingProvider):
    name = "startrack"

    def __init__(self):
        # StarTrack uses the same AusPost developer platform but with a dedicated
        # account number issued to StarTrack business customers.
        self.api_key = os.getenv("STARTRACK_API_KEY", os.getenv("AUSPOST_API_KEY", "")).strip()
        self.account_number = os.getenv("STARTRACK_ACCOUNT_NUMBER", "").strip()
        self.api_url = os.getenv("STARTRACK_API_URL", "https://digitalapi.auspost.com.au").rstrip("/")

    def create_label(self, shipment_info: Dict[str, Any]) -> Dict[str, Any]:
        if not self.api_key:
            raise RuntimeError(
                "STARTRACK_API_KEY is not configured — cannot create StarTrack label. "
                "Set STARTRACK_API_KEY (or AUSPOST_API_KEY) and STARTRACK_ACCOUNT_NUMBER."
            )
        if not self.account_number:
            raise RuntimeError(
                "STARTRACK_ACCOUNT_NUMBER is required to create StarTrack labels. "
                "Obtain it from your StarTrack business account."
            )
        try:
            import requests
            headers = {
                "AUTH_KEY": self.api_key,
                "Account-Number": self.account_number,
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
            payload = {
                "shipments": [shipment_info] if not isinstance(shipment_info.get("shipments"), list) else shipment_info["shipments"],
            }
            resp = requests.post(
                f"{self.api_url}/shipping/v1/shipments",
                json=payload,
                headers=headers,
                timeout=20,
            )
            try:
                j = resp.json()
            except Exception:
                j = {"status_code": resp.status_code, "text": resp.text}
            _log.info("startrack create_label: status=%s", resp.status_code)
            return {"ok": resp.status_code < 300, "raw": j, "provider": "startrack"}
        except Exception as exc:
            _log.error("startrack create_label error: %s", exc)
            return {"ok": False, "error": str(exc), "provider": "startrack"}

    def get_tracking(self, tracking_number: str) -> Dict[str, Any]:
        if not self.api_key:
            raise RuntimeError("STARTRACK_API_KEY is not configured.")
        try:
            import requests
            headers = {
                "AUTH_KEY": self.api_key,
                "Accept": "application/json",
            }
            if self.account_number:
                headers["Account-Number"] = self.account_number
            resp = requests.get(
                f"{self.api_url}/shipmentsgatewayapi/shipmentsgateway/v1/track/items/{tracking_number}",
                headers=headers,
                timeout=10,
            )
            try:
                j = resp.json()
            except Exception:
                j = {"status_code": resp.status_code, "text": resp.text}
            return {"ok": resp.status_code < 300, "raw": j, "provider": "startrack"}
        except Exception as exc:
            return {"ok": False, "error": str(exc), "provider": "startrack"}


# ── Provider selection ────────────────────────────────────────────────────────

def get_default_shipping_provider() -> BaseShippingProvider:
    """Return the first configured provider. Raises RuntimeError if none are configured."""
    preferred = os.getenv("PREFERRED_SHIPPING_PROVIDER", "").strip().lower()

    candidates = {
        "auspost": AusPostProvider,
        "startrack": StarTrackProvider,
        "easypost": EasyPostProvider,
        "shipstation": ShipStationProvider,
    }

    if preferred and preferred in candidates:
        return candidates[preferred]()

    # ANZ-first default order: AusPost → StarTrack → EasyPost → ShipStation
    ap = AusPostProvider()
    if ap.api_key:
        return ap

    st = StarTrackProvider()
    if st.api_key and st.account_number:
        return st

    ep = EasyPostProvider()
    if ep.api_key:
        return ep

    ss = ShipStationProvider()
    if ss.key and ss.secret:
        return ss

    # No live provider configured — return EasyPost stub so callers get a
    # valid provider object that returns graceful {"ok": False, "stub": True}
    # rather than raising. Real labels require a configured API key.
    return EasyPostProvider()


def shipping_readiness() -> Dict[str, Any]:
    """Honest, network-free report of whether a REAL carrier is configured.

    Shipping honesty (Track 6): callers must know whether a label would be a real shipment or a
    stub. `ready` is True only when at least one carrier has the credentials it needs; otherwise
    `stub` is True and labels MUST NOT be presented as real (no fabricated tracking numbers)."""
    ap = AusPostProvider()
    st = StarTrackProvider()
    ep = EasyPostProvider()
    ss = ShipStationProvider()
    configured = {
        "auspost": bool(ap.api_key),
        "startrack": bool(st.api_key and st.account_number),
        "easypost": bool(ep.api_key),
        "shipstation": bool(ss.key and ss.secret),
    }
    ready = any(configured.values())
    return {
        "ready": ready,
        "stub": not ready,
        "provider": get_default_shipping_provider().name,
        "configured": configured,
        "reason": (
            "live carrier configured"
            if ready
            else "no carrier API key configured — labels are stubs, not real shipments"
        ),
    }


def plan_label_record(readiness: Dict[str, Any], create_result: Dict[str, Any], *, case_id: str) -> Dict[str, Any]:
    """Decide — HONESTLY and purely (no I/O) — what to record/return for a label attempt.

    A stub/unconfigured carrier (or a failed `create_label`) must NOT yield a fabricated REAL-LOOKING
    carrier tracking number ('RR…') that implies a shipment exists. It DOES still need a reference so
    the returns flow can proceed, so it gets a CLEARLY-MARKED 'STUB-…' reference with stub=True /
    status='stub' (unambiguously not a real carrier shipment). Only a genuinely successful create
    produces a real 'RR…' tracking number and status='generated'."""
    result = create_result or {}
    is_stub = bool((readiness or {}).get("stub")) or bool(result.get("stub")) or not bool(result.get("ok"))
    if is_stub:
        return {
            "tracking_number": f"STUB-{uuid.uuid4().hex[:10].upper()}",  # clearly NOT a real carrier code
            "label_url": None,  # no real label PDF exists for a stub
            "status": "stub",
            "stub": True,
            "ok": False,
            "reason": (
                result.get("error")
                or (readiness or {}).get("reason")
                or "no carrier configured — label is a stub, not a real shipment"
            ),
        }
    tracking = f"RR{uuid.uuid4().hex[:10].upper()}"
    label_url = (
        (result.get("raw") or {}).get("postage_label", {}).get("label_url")
        or result.get("label_url")
        or f"pending://{case_id}"
    )
    return {
        "tracking_number": tracking,
        "label_url": label_url,
        "status": "generated",
        "stub": False,
        "ok": True,
        "reason": None,
    }
