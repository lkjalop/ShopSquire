"""ShopSquireClient — Async HTTP client with typed sub-resources."""
from __future__ import annotations

import os
from typing import Any

import httpx

from shopsquire_sdk.exceptions import raise_for_status
from shopsquire_sdk.models import (
    ApiVersionInfo,
    Cart,
    DecisionTrace,
    HealthStatus,
    Order,
    Product,
    RecommendResult,
)

DEFAULT_TIMEOUT = 30.0


class _Resource:
    def __init__(self, client: "ShopSquireClient") -> None:
        self._c = client

    async def _get(self, path: str, **params) -> Any:
        return await self._c._request("GET", path, params=params)

    async def _post(self, path: str, json: Any = None, **params) -> Any:
        return await self._c._request("POST", path, json=json, params=params)

    async def _delete(self, path: str, **params) -> Any:
        return await self._c._request("DELETE", path, params=params)


class ProductsResource(_Resource):
    async def search(self, query: str, limit: int = 10, uid: str = "api-user") -> list[Product]:
        data = await self._get("/api/v1/recommend", q=query, limit=limit, uid=uid)
        results = data.get("results") or data.get("products") or []
        return [Product.model_validate(r) for r in results]

    async def get(self, sku: str) -> Product:
        data = await self._get(f"/api/v1/products/{sku}")
        return Product.model_validate(data)

    async def compare(self, skus: list[str]) -> list[Product]:
        data = await self._post("/api/v1/products/compare", json={"skus": skus})
        return [Product.model_validate(p) for p in (data.get("products") or [])]


class CartResource(_Resource):
    async def get(self, uid: str) -> Cart:
        data = await self._get("/api/v1/cart", uid=uid)
        return Cart.model_validate({**data, "uid": uid})

    async def add(self, uid: str, sku: str, quantity: int = 1) -> Cart:
        data = await self._post("/api/v1/cart/add", json={"uid": uid, "sku": sku, "quantity": quantity})
        return Cart.model_validate({**data, "uid": uid})

    async def remove(self, uid: str, sku: str) -> Cart:
        data = await self._post("/api/v1/cart/remove", json={"uid": uid, "sku": sku})
        return Cart.model_validate({**data, "uid": uid})

    async def clear(self, uid: str) -> Cart:
        data = await self._post("/api/v1/cart/clear", json={"uid": uid})
        return Cart.model_validate({**data, "uid": uid})

    async def checkout(self, uid: str) -> Order:
        data = await self._post("/api/v1/cart/checkout", json={"uid": uid})
        return Order.model_validate(data)


class RecommendResource(_Resource):
    async def query(
        self,
        q: str,
        uid: str = "api-user",
        limit: int = 10,
        budget_max: float | None = None,
        brand: str | None = None,
    ) -> list[RecommendResult]:
        params: dict[str, Any] = {"q": q, "uid": uid, "limit": limit}
        if budget_max is not None:
            params["budget_max"] = budget_max
        if brand:
            params["brand"] = brand
        data = await self._get("/api/v1/recommend", **params)
        results = data.get("results") or []
        return [RecommendResult.model_validate(r) for r in results]


class OrdersResource(_Resource):
    async def get(self, order_id: str) -> Order:
        data = await self._get(f"/api/v1/orders/{order_id}")
        return Order.model_validate(data)

    async def list(self, uid: str, limit: int = 20) -> list[Order]:
        data = await self._get("/api/v1/orders", uid=uid, limit=limit)
        return [Order.model_validate(o) for o in (data.get("orders") or data if isinstance(data, list) else [])]


class DecisionsResource(_Resource):
    async def get_trace(self, trace_id: str) -> DecisionTrace:
        data = await self._get(f"/api/v1/decisions/trace/{trace_id}")
        return DecisionTrace.model_validate({**data, "trace_id": trace_id})


class ShopSquireClient:
    """Async ShopSquire API client.

    Usage::

        async with ShopSquireClient(base_url="https://api.shopsquire.io", api_key="...") as c:
            results = await c.products.search("laptop")

    Or without context manager::

        client = ShopSquireClient(...)
        await client.aopen()
        # ... use client ...
        await client.aclose()
    """

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        headers: dict[str, str] | None = None,
    ) -> None:
        self._base_url = (base_url or os.getenv("SHOPSQUIRE_API_URL", "http://localhost:8080")).rstrip("/")
        self._api_key = api_key or os.getenv("SHOPSQUIRE_API_KEY", "")
        self._timeout = timeout
        self._extra_headers = headers or {}
        self._http: httpx.AsyncClient | None = None

        # Sub-resources
        self.products = ProductsResource(self)
        self.cart = CartResource(self)
        self.recommend = RecommendResource(self)
        self.orders = OrdersResource(self)
        self.decisions = DecisionsResource(self)

    def _build_headers(self) -> dict[str, str]:
        h = {"Content-Type": "application/json", "Accept": "application/json"}
        if self._api_key:
            h["x-api-key"] = self._api_key
        h.update(self._extra_headers)
        return h

    async def aopen(self) -> None:
        if self._http is None:
            self._http = httpx.AsyncClient(
                base_url=self._base_url,
                headers=self._build_headers(),
                timeout=self._timeout,
            )

    async def aclose(self) -> None:
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    async def __aenter__(self) -> "ShopSquireClient":
        await self.aopen()
        return self

    async def __aexit__(self, *_) -> None:
        await self.aclose()

    async def _request(self, method: str, path: str, **kwargs) -> Any:
        if self._http is None:
            await self.aopen()
        assert self._http is not None
        resp = await self._http.request(method, path, **kwargs)
        try:
            body = resp.json()
        except Exception:
            body = {"message": resp.text}
        raise_for_status(resp.status_code, body)
        return body

    async def health(self) -> HealthStatus:
        data = await self._request("GET", "/healthz")
        return HealthStatus.model_validate(data)

    async def api_version(self) -> ApiVersionInfo:
        data = await self._request("GET", "/api/version")
        return ApiVersionInfo.model_validate(data)
