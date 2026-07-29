from __future__ import annotations

import logging
import os
from typing import Any

from src.app.erp.connectors.base import InventoryConnector, InventoryRecord
from src.app.security.url_guard import ensure_safe_outbound_url


logger = logging.getLogger(__name__)


class ShopifyInventoryConnector:
    """Read-only Shopify inventory connector.

    Environment variables:
      - SHOPIFY_SHOP: e.g. "myshop.myshopify.com"
      - SHOPIFY_ACCESS_TOKEN: admin API access token
      - SHOPIFY_API_VERSION: default "2024-10"
      - SHOPIFY_WAREHOUSE: optional warehouse label (default "shopify")

    Notes:
      - Uses REST products endpoint and variant `inventory_quantity` for MVP simplicity.
      - For large catalogs, use a GraphQL + bulk operation connector.
    """

    def __init__(
        self,
        *,
        shop: str | None = None,
        access_token: str | None = None,
        api_version: str | None = None,
        warehouse: str | None = None,
    ):
        self.shop = shop or os.getenv("SHOPIFY_SHOP") or ""
        self.access_token = access_token or os.getenv("SHOPIFY_ACCESS_TOKEN") or ""
        self.api_version = api_version or os.getenv("SHOPIFY_API_VERSION") or "2024-10"
        self.warehouse = warehouse or os.getenv("SHOPIFY_WAREHOUSE") or "shopify"

    def name(self) -> str:
        return "shopify"

    def health(self) -> dict[str, Any]:
        if not self.shop:
            return {"ok": False, "error": "SHOPIFY_SHOP not set"}
        if not self.access_token:
            return {"ok": False, "error": "SHOPIFY_ACCESS_TOKEN not set"}
        return {"ok": True, "shop": self.shop, "api_version": self.api_version, "warehouse": self.warehouse}

    def _base_url(self) -> str:
        shop = self.shop.replace("https://", "").replace("http://", "").strip().strip("/")
        base = f"https://{shop}/admin/api/{self.api_version}"
        ensure_safe_outbound_url(base)
        return base

    def fetch_inventory(self, *, tenant_id: str | None = None) -> list[InventoryRecord]:
        if not self.health().get("ok"):
            return []
        try:
            import requests
        except Exception:
            return []

        headers = {
            "X-Shopify-Access-Token": self.access_token,
            "Accept": "application/json",
        }
        url = f"{self._base_url()}/products.json"
        params = {"limit": 250, "fields": "id,updated_at,variants"}

        out: list[InventoryRecord] = []
        next_url: str | None = None

        for _page in range(1, 50):  # hard cap for safety
            try:
                if next_url:
                    ensure_safe_outbound_url(next_url)
                    resp = requests.get(next_url, headers=headers, timeout=10)
                else:
                    ensure_safe_outbound_url(url)
                    resp = requests.get(url, headers=headers, params=params, timeout=10)
                resp.raise_for_status()
                data = resp.json() or {}
            except Exception:
                break

            try:
                products = data.get("products") or []
            except Exception:
                products = []

            for p in products:
                try:
                    updated_at = str(p.get("updated_at") or "") or None
                    for v in (p.get("variants") or []):
                        sku = str(v.get("sku") or "").strip()
                        if not sku:
                            continue
                        try:
                            stock = int(v.get("inventory_quantity") or 0)
                        except Exception:
                            stock = 0
                        out.append(
                            InventoryRecord(
                                sku=sku,
                                warehouse=self.warehouse,
                                stock=stock,
                                updated_at=updated_at,
                                source=self.name(),
                            )
                        )
                except Exception as exc:
                    logger.warning(
                        "Shopify product record skipped warehouse=%s: %s",
                        self.warehouse,
                        exc,
                    )
                    continue

            # Pagination: Shopify REST uses Link header
            try:
                link = resp.headers.get("Link") or resp.headers.get("link") or ""
                nxt = None
                for part in link.split(","):
                    if 'rel="next"' in part:
                        seg = part.split(";")[0].strip()
                        if seg.startswith("<") and seg.endswith(">"):
                            nxt = seg[1:-1]
                next_url = nxt
            except Exception:
                next_url = None

            if not next_url:
                break

        return out


def create_connector() -> InventoryConnector:
    return ShopifyInventoryConnector()
