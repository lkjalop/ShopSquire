from __future__ import annotations

import os
from typing import Any, Dict, List

import requests

from src.app.erp.connectors.base import InventoryConnector, InventoryRecord
from src.app.security.url_guard import ensure_safe_outbound_url


class HTTPInventoryConnector(InventoryConnector):
    """Generic HTTP pull connector for ERP/procurement inventory snapshots."""

    def __init__(self, *, provider_id: str, env_prefix: str):
        self.provider_id = str(provider_id)
        self.env_prefix = str(env_prefix).upper()

    def name(self) -> str:
        return f"http_inventory:{self.provider_id}"

    def _cfg(self) -> Dict[str, str]:
        p = self.env_prefix
        return {
            "base_url": str(os.getenv(f"{p}_BASE_URL", "")).strip(),
            "inventory_path": str(os.getenv(f"{p}_INVENTORY_PATH", "/inventory")).strip() or "/inventory",
            "api_key": str(os.getenv(f"{p}_API_KEY", "")).strip(),
            "bearer_token": str(os.getenv(f"{p}_BEARER_TOKEN", "")).strip(),
            "client_id": str(os.getenv(f"{p}_CLIENT_ID", "")).strip(),
            "client_secret": str(os.getenv(f"{p}_CLIENT_SECRET", "")).strip(),
            "token_url": str(os.getenv(f"{p}_TOKEN_URL", "")).strip(),
            "scope": str(os.getenv(f"{p}_SCOPE", "")).strip(),
        }

    def _headers(self, cfg: Dict[str, str]) -> Dict[str, str]:
        h = {"accept": "application/json"}
        if cfg.get("api_key"):
            h["x-api-key"] = cfg["api_key"]
        if cfg.get("bearer_token"):
            h["authorization"] = f"Bearer {cfg['bearer_token']}"
        elif cfg.get("token_url") and cfg.get("client_id") and cfg.get("client_secret"):
            try:
                ensure_safe_outbound_url(cfg["token_url"])
                r = requests.post(
                    cfg["token_url"],
                    data={
                        "grant_type": "client_credentials",
                        "client_id": cfg["client_id"],
                        "client_secret": cfg["client_secret"],
                        "scope": cfg.get("scope") or None,
                    },
                    timeout=8.0,
                )
                if 200 <= int(r.status_code) < 300:
                    tok = str((r.json() or {}).get("access_token") or "")
                    if tok:
                        h["authorization"] = f"Bearer {tok}"
            except Exception:
                pass
        return h

    def _endpoint(self, cfg: Dict[str, str]) -> str:
        base = (cfg.get("base_url") or "").rstrip("/")
        path = "/" + (cfg.get("inventory_path") or "/inventory").lstrip("/")
        out = f"{base}{path}"
        ensure_safe_outbound_url(out)
        return out

    def health(self) -> Dict[str, Any]:
        cfg = self._cfg()
        if not cfg.get("base_url"):
            return {"ok": False, "error": "missing_base_url", "provider": self.provider_id}
        try:
            r = requests.get(self._endpoint(cfg), headers=self._headers(cfg), timeout=6.0)
            if int(r.status_code) in (401, 403):
                return {"ok": False, "error": "auth_failed", "provider": self.provider_id, "status_code": int(r.status_code)}
            if int(r.status_code) >= 500:
                return {"ok": False, "error": "provider_5xx", "provider": self.provider_id, "status_code": int(r.status_code)}
            if int(r.status_code) == 429:
                return {"ok": False, "error": "provider_rate_limited", "provider": self.provider_id, "status_code": 429}
            return {"ok": True, "provider": self.provider_id, "status_code": int(r.status_code)}
        except Exception as exc:
            return {"ok": False, "error": str(exc), "provider": self.provider_id}

    def fetch_inventory(self, *, tenant_id: str | None = None) -> List[InventoryRecord]:
        cfg = self._cfg()
        if not cfg.get("base_url"):
            return []
        r = requests.get(self._endpoint(cfg), headers=self._headers(cfg), timeout=12.0)
        r.raise_for_status()
        body = r.json()
        rows = body.get("items") if isinstance(body, dict) else body
        if not isinstance(rows, list):
            return []
        out: List[InventoryRecord] = []
        for row in rows[:20000]:
            if not isinstance(row, dict):
                continue
            sku = str(row.get("sku") or "").strip()
            if not sku:
                continue
            out.append(
                InventoryRecord(
                    sku=sku,
                    warehouse=str(row.get("warehouse") or row.get("location") or "default"),
                    stock=int(row.get("stock") or row.get("qty") or 0),
                    updated_at=(str(row.get("updated_at")) if row.get("updated_at") else None),
                    source=self.provider_id,
                )
            )
        return out

