from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

import requests

from src.app.erp.connector_runtime import (
    TOKEN_CACHE,
    ConnectorOutcome,
    ConnectorOutcomeType,
    JobBudget,
    compare_and_set_cursor,
    get_cursor_state,
    retry_after_seconds,
)
from src.app.erp.connectors.base import InventoryConnector, InventoryRecord
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
        self.job_budget_seconds = float(os.getenv("NETSUITE_JOB_BUDGET_SEC", "30") or 30)
        self.subscription_id = str(os.getenv("NETSUITE_SUBSCRIPTION_ID", "default") or "default").strip()

    def name(self) -> str:
        return "netsuite"

    def get_cursor(self, *, tenant_id: str | None, entity_type: str = "inventory") -> str | None:
        return get_cursor_state(
            tenant_id=tenant_id,
            provider="netsuite",
            subscription_id=self.subscription_id,
            entity_type=entity_type,
        ).cursor

    def set_cursor(
        self,
        *,
        tenant_id: str | None,
        cursor_value: str | None,
        entity_type: str = "inventory",
        expected_version: int | None = None,
        checkpoint: Dict[str, Any] | None = None,
    ) -> None:
        state = get_cursor_state(
            tenant_id=tenant_id,
            provider="netsuite",
            subscription_id=self.subscription_id,
            entity_type=entity_type,
        )
        compare_and_set_cursor(
            tenant_id=tenant_id,
            provider="netsuite",
            subscription_id=self.subscription_id,
            entity_type=entity_type,
            expected_version=state.version if expected_version is None else int(expected_version),
            cursor_value=cursor_value,
            checkpoint=checkpoint,
        )

    def _auth_headers(self, *, tenant_id: str | None = None) -> Dict[str, str]:
        h = {"accept": "application/json", "content-type": "application/json"}
        if self.api_key:
            h["x-api-key"] = self.api_key
        if self.bearer_token:
            h["authorization"] = f"Bearer {self.bearer_token}"
            return h
        if self.token_url and self.client_id and self.client_secret:
            cached = TOKEN_CACHE.get(
                tenant_id=tenant_id,
                provider="netsuite",
                subscription_id=self.subscription_id,
            )
            if cached:
                h["authorization"] = f"Bearer {cached}"
                return h
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
            r.raise_for_status()
            body = r.json()
            tok = str((body or {}).get("access_token") or "")
            if not tok:
                raise RuntimeError("netsuite_token_missing")
            TOKEN_CACHE.put(
                tenant_id=tenant_id,
                provider="netsuite",
                subscription_id=self.subscription_id,
                token=tok,
                expires_in_seconds=float((body or {}).get("expires_in") or 300),
            )
            h["authorization"] = f"Bearer {tok}"
        return h

    def _req(
        self,
        method: str,
        path: str,
        *,
        params: Dict[str, Any] | None = None,
        payload: Dict[str, Any] | None = None,
        tenant_id: str | None = None,
        budget: JobBudget | None = None,
    ) -> requests.Response:
        url = f"{self.base_url}/{path.lstrip('/')}"
        ensure_safe_outbound_url(url)
        headers = self._auth_headers(tenant_id=tenant_id)
        job_budget = budget or JobBudget(self.job_budget_seconds)
        last = None
        for attempt in range(max(1, self.max_retries)):
            try:
                remaining = job_budget.require_remaining()
                r = requests.request(
                    method=method.upper(),
                    url=url,
                    params=params,
                    json=payload,
                    headers=headers,
                    timeout=max(0.1, min(15.0, remaining)),
                )
                if int(r.status_code) in (429, 500, 502, 503, 504) and attempt < self.max_retries - 1:
                    delay = retry_after_seconds(r.headers.get("retry-after"))
                    if delay is None:
                        delay = (self.backoff_ms / 1000.0) * float(2**attempt)
                    time.sleep(min(delay, job_budget.require_remaining()))
                    continue
                return r
            except Exception as exc:
                last = exc
                if attempt < self.max_retries - 1:
                    delay = (self.backoff_ms / 1000.0) * float(2**attempt)
                    time.sleep(min(delay, job_budget.require_remaining()))
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
            if int(r.status_code) >= 400:
                return {
                    "ok": False,
                    "error": "provider_http_error",
                    "provider": "netsuite",
                    "status_code": int(r.status_code),
                }
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
        r = self._req("GET", self.inventory_path, params=params, tenant_id=tenant_id)
        if int(r.status_code) == 204:
            return [], cursor
        r.raise_for_status()
        if "application/json" not in str(r.headers.get("content-type") or "").lower():
            raise RuntimeError("netsuite_inventory_invalid_content_type")
        body = r.json()
        items = body.get("items") if isinstance(body, dict) else body
        if not isinstance(items, list):
            raise RuntimeError("netsuite_inventory_malformed_payload")
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

    def fetch_inventory_outcome(
        self, *, tenant_id: str | None = None
    ) -> ConnectorOutcome[List[InventoryRecord]]:
        try:
            rows = self.fetch_inventory(tenant_id=tenant_id)
            return ConnectorOutcome(
                ConnectorOutcomeType.OBSERVED if rows else ConnectorOutcomeType.EMPTY,
                rows,
            )
        except requests.HTTPError as exc:
            status = int(getattr(getattr(exc, "response", None), "status_code", 0) or 0)
            outcome = (
                ConnectorOutcomeType.UNAUTHORISED
                if status in (401, 403)
                else ConnectorOutcomeType.UNAVAILABLE
            )
            return ConnectorOutcome(outcome, [], error=f"http_{status or 'error'}")
        except (TypeError, ValueError) as exc:
            return ConnectorOutcome(ConnectorOutcomeType.MALFORMED, [], error=str(exc))
        except Exception as exc:
            detail = str(exc)
            outcome = (
                ConnectorOutcomeType.MALFORMED
                if "malformed" in detail or "invalid_content_type" in detail
                else ConnectorOutcomeType.UNAVAILABLE
            )
            return ConnectorOutcome(outcome, [], error=detail)

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
