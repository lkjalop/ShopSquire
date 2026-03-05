"""Pydantic models for ShopSquire API responses."""
from __future__ import annotations
from typing import Any
from pydantic import BaseModel, Field


class Product(BaseModel):
    sku: str
    name: str
    brand: str | None = None
    price_cents: int | None = None
    currency: str = "USD"
    specs: dict[str, Any] = Field(default_factory=dict)
    image_url: str | None = None
    active: bool = True

    @property
    def price(self) -> float:
        return (self.price_cents or 0) / 100


class CartItem(BaseModel):
    sku: str
    name: str | None = None
    quantity: int
    price_cents: int | None = None


class Cart(BaseModel):
    cart_id: str
    uid: str | None = None
    items: list[CartItem] = Field(default_factory=list)
    subtotal_cents: int = 0
    currency: str = "USD"

    @property
    def subtotal(self) -> float:
        return self.subtotal_cents / 100


class Order(BaseModel):
    id: str
    status: str
    total_cents: int
    currency: str = "USD"
    customer_id: str | None = None
    guest_email: str | None = None
    created_at: str | None = None

    @property
    def total(self) -> float:
        return self.total_cents / 100


class RecommendResult(BaseModel):
    sku: str
    name: str | None = None
    score: float | None = None
    reason: str | None = None
    price_cents: int | None = None


class DecisionTrace(BaseModel):
    trace_id: str
    agent_name: str | None = None
    decision: str | None = None
    reasoning: str | None = None
    created_at: str | None = None
    steps: list[dict[str, Any]] = Field(default_factory=list)


class HealthStatus(BaseModel):
    status: str
    version: str | None = None
    db: str | None = None
    redis: str | None = None


class ApiVersionInfo(BaseModel):
    current_version: str
    deprecated_versions: list[str] = Field(default_factory=list)
    sunset: dict[str, str] = Field(default_factory=dict)
    migration_guide: str | None = None
