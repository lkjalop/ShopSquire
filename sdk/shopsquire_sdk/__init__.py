"""shopsquire_sdk — Type-safe Python client for the ShopSquire API.

Quick start::

    from shopsquire_sdk import ShopSquireClient

    async with ShopSquireClient(base_url="https://api.shopsquire.io", api_key="...") as client:
        products = await client.products.search("gaming laptop")
        cart = await client.cart.add(uid="user-1", sku="sku-123", quantity=1)

All methods return typed Pydantic models and raise ``ShopSquireError`` on
4xx / 5xx responses so callers can handle errors precisely.
"""
from shopsquire_sdk.client import ShopSquireClient
from shopsquire_sdk.exceptions import (
    ShopSquireError,
    NotFoundError,
    AuthenticationError,
    AuthorizationError,
    RateLimitError,
    ValidationError,
    ServerError,
)
from shopsquire_sdk.models import (
    Product,
    CartItem,
    Cart,
    Order,
    RecommendResult,
    DecisionTrace,
    HealthStatus,
    ApiVersionInfo,
)

__version__ = "0.1.0"

__all__ = [
    "ShopSquireClient",
    # Exceptions
    "ShopSquireError",
    "NotFoundError",
    "AuthenticationError",
    "AuthorizationError",
    "RateLimitError",
    "ValidationError",
    "ServerError",
    # Models
    "Product",
    "CartItem",
    "Cart",
    "Order",
    "RecommendResult",
    "DecisionTrace",
    "HealthStatus",
    "ApiVersionInfo",
]
