from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import requests
from sqlalchemy import text

from src.app.erp.connectors.base import InventoryConnector, InventoryRecord
from src.app.models.db import db_session
from src.app.security.url_guard import ensure_safe_outbound_url


@dataclass(frozen=True)
class NetSuiteCustomer:
    external_id: str
    email: str
    name: str


@dataclass(frozen=True)
class NetSuiteSalesOrder:
    external_id: str
    customer_external_id: str
    currency: str
    total_cents: int
    line_items: List[Dict[str, Any]]


class NetSuiteConnector(InventoryConnector):
    def __init__(self) -> None:
        self.base_url = str(os.getenv("NETSUITE_BASE_URL", "")).rstrip("/")
        self.inventory_path = str(os.getenv("NETSUITE_INVENTORY_PATH", "/inventory/delta") or "/inventory/delta")
        self.token_url = str(os.getenv("NETSUITE_TOKEN_URL", "")).strip()
        self.client_id = str(os.getenv("NETSUITE_CLIENT_ID", "")).strip()
        self.client_secret = str(os.getenv("NETSUITE_CLIENT_SECRET", "")).strip()
        self.api_key = str(os.getenv("NETSUITE_API_KEY", "")).strip()
        self.bearer_token = str(os.getenv("NETSUITE_BEARER_TOKEN", "")).strip()
        self.customer_upsert_path = str(os.getenv("NETSUITE_CUSTOMER_UPSERT_PATH", "/customers/upsert") or "/customers/upsert")
        self.sales_order_upsert_path = str(os.getenv("NETSUITE_SALES_ORDER_UPSERT_PATH", "/sales_orders/upsert") or "/sales_orders/upsert")
        self.max_retries = int(os.getenv("NETSUITE_HTTP_MAX_RETRIES", "3") or 3)
        self.backoff_ms = int(os.getenv("NETSUITE_HTTP_BACKOFF_MS", "250") or 250)

    def name(self) -> str:
        return "netsuite"

    def _ensure_state_table(self) -> None:
        try:
            with db_session() as db:
                db.execute(
                    text(
                        """
                        CREATE TABLE IF NOT EXISTS erp_sync_state (
                            id TEXT PRIMARY KEY,
                            tenant_id TEXT,
                            provider TEXT NOT NULL,
                            entity_type TEXT NOT NULL,
                            cursor_value TEXT,
                            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                        )
                        """
                    )
                )
                db.execute(
                    text(
                        "CREATE UNIQUE INDEX IF NOT EXISTS idx_erp_sync_state_unique ON erp_sync_state(tenant_id, provider, entity_type)"
                    )
                )
                db.commit()
        except Exception:
            pass

    def get_cursor(self, *, tenant_id: str | None, entity_type: str = "inventory") -> str | None:
        self._ensure_state_table()
        try:
            with db_session() as db:
                row = db.execute(
                    text(
                        """
                        SELECT cursor_value
                        FROM erp_sync_state
                        WHERE provider = 'netsuite' AND entity_type = :entity_type
                          AND (tenant_id = :tenant_id OR (tenant_id IS NULL AND :tenant_id IS NULL))
                        LIMIT 1
                        """
                    ),
                    {"tenant_id": tenant_id, "entity_type": entity_type},
                ).fetchone()
            return str(row[0]) if row and row[0] is not None else None
        except Exception:
            return None

    def set_cursor(self, *, tenant_id: str | None, cursor_value: str | None, entity_type: str = "inventory") -> None:
        self._ensure_state_table()
        sid = f"erpstate:netsuite:{entity_type}:{tenant_id or 'global'}"
        try:
            with db_session() as db:
                db.execute(
                    text(
                        """
                        INSERT INTO erp_sync_state (id, tenant_id, provider, entity_type, cursor_value, updated_at)
                        VALUES (:id, :tenant_id, 'netsuite', :entity_type, :cursor_value, CURRENT_TIMESTAMP)
                        ON CONFLICT(tenant_id, provider, entity_type)
                        DO UPDATE SET cursor_value = excluded.cursor_value, updated_at = CURRENT_TIMESTAMP
                        """
                    ),
                    {"id": sid, "tenant_id": tenant_id, "entity_type": entity_type, "cursor_value": cursor_value},
                )
                db.commit()
        except Exception:
            pass

    def _auth_headers(self) -> Dict[str, str]:
        h = {"accept": "application/json", "content-type": "application/json"}
        if self.api_key:
            h["x-api-key"] = self.api_key
        if self.bearer_token:
            h["authorization"] = f"Bearer {self.bearer_token}"
            return h
        if self.token_url and self.client_id and self.client_secret:
            try:
                ensure_safe_outbound_url(self.token_url)
                r = requests.post(
                    self.token_url,
                    data={
                        "grant_type": "client_credentials",
                        "client_id": self.client_id,
                        "client_secret": self.client_secret,
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

    def _req(self, method: str, path: str, *, params: Dict[str, Any] | None = None, payload: Dict[str, Any] | None = None) -> requests.Response:
        url = f"{self.base_url}/{path.lstrip('/')}"
        ensure_safe_outbound_url(url)
        headers = self._auth_headers()
        last = None
        for attempt in range(max(1, self.max_retries)):
            try:
                r = requests.request(method=method.upper(), url=url, params=params, json=payload, headers=headers, timeout=15.0)
                if int(r.status_code) in (429, 500, 502, 503, 504) and attempt < self.max_retries - 1:
                    time.sleep((self.backoff_ms / 1000.0) * float(2**attempt))
                    continue
                return r
            except Exception as exc:
                last = exc
                if attempt < self.max_retries - 1:
                    time.sleep((self.backoff_ms / 1000.0) * float(2**attempt))
                    continue
                raise
        if last:
            raise last
        raise RuntimeError("netsuite_request_failed")

    def health(self) -> Dict[str, Any]:
        if not self.base_url:
            return {"ok": False, "error": "missing_base_url", "provider": "netsuite"}
        try:
            r = self._req("GET", self.inventory_path, params={"limit": 1})
            if int(r.status_code) == 429:
                return {"ok": False, "error": "provider_rate_limited", "provider": "netsuite", "status_code": 429}
            if int(r.status_code) >= 500:
                return {"ok": False, "error": "provider_5xx", "provider": "netsuite", "status_code": int(r.status_code)}
            if int(r.status_code) in (401, 403):
                return {"ok": False, "error": "auth_failed", "provider": "netsuite", "status_code": int(r.status_code)}
            return {"ok": True, "provider": "netsuite", "status_code": int(r.status_code)}
        except Exception as exc:
            return {"ok": False, "error": str(exc), "provider": "netsuite"}

    def fetch_inventory_delta(self, *, cursor: str | None = None, tenant_id: str | None = None, limit: int = 2000) -> Tuple[List[InventoryRecord], str | None]:
        if not self.base_url:
            return [], cursor
        params: Dict[str, Any] = {"limit": max(1, min(int(limit or 2000), 10000))}
        if cursor:
            params["cursor"] = cursor
        if tenant_id:
            params["tenant_id"] = tenant_id
        r = self._req("GET", self.inventory_path, params=params)
        if int(r.status_code) == 204:
            return [], cursor
        r.raise_for_status()
        body = r.json() if "application/json" in str(r.headers.get("content-type") or "") else {}
        items = body.get("items") if isinstance(body, dict) else body
        if not isinstance(items, list):
            items = []
        out: List[InventoryRecord] = []
        for row in items:
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
                    source="netsuite",
                )
            )
        next_cursor = str(body.get("next_cursor")) if isinstance(body, dict) and body.get("next_cursor") is not None else cursor
        return out, next_cursor

    def fetch_inventory(self, *, tenant_id: str | None = None) -> List[InventoryRecord]:
        cursor = self.get_cursor(tenant_id=tenant_id, entity_type="inventory")
        rows, next_cursor = self.fetch_inventory_delta(cursor=cursor, tenant_id=tenant_id)
        # Cursor advancement is controlled by sync job path; keep fetch side-effect free.
        _ = next_cursor
        return rows

    def push_customer(self, c: NetSuiteCustomer) -> Dict[str, Any]:
        payload = {"external_id": c.external_id, "email": c.email, "name": c.name}
        r = self._req("POST", self.customer_upsert_path, payload=payload)
        if int(r.status_code) in (200, 201, 202):
            return {"ok": True, "status_code": int(r.status_code)}
        return {"ok": False, "status_code": int(r.status_code), "detail": str(r.text)[:300]}

    def push_sales_order(self, o: NetSuiteSalesOrder) -> Dict[str, Any]:
        payload = {
            "external_id": o.external_id,
            "customer_external_id": o.customer_external_id,
            "currency": o.currency,
            "total_cents": int(o.total_cents),
            "line_items": o.line_items,
        }
        r = self._req("POST", self.sales_order_upsert_path, payload=payload)
        if int(r.status_code) in (200, 201, 202):
            return {"ok": True, "status_code": int(r.status_code)}
        return {"ok": False, "status_code": int(r.status_code), "detail": str(r.text)[:300]}

