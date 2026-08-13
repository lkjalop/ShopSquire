from fastapi import FastAPI

from src.app.bootstrap.storefront_router_group import register_storefront_router_group


def test_storefront_router_group_registers_buyer_and_post_order_surfaces():
    app = FastAPI()
    registered = register_storefront_router_group(app)
    paths = {route.path for route in app.routes}

    assert {"pricing", "inventory", "support", "events", "payments"} <= set(registered)
    assert {"returns", "fraud"} <= set(registered)
    assert "/api/v1/orders/{order_id}/cancel" not in paths
    assert any(path.startswith("/api/v1/returns") for path in paths)
    assert any("payments" in path for path in paths)
