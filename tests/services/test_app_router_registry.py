import pytest
from fastapi import APIRouter, FastAPI

from src.app.app_router_registry import register_routers, router_registration


def test_typed_router_registry_preserves_order_and_records_names():
    first, second = APIRouter(), APIRouter()
    first.add_api_route("/first", lambda: {"ok": 1})
    second.add_api_route("/second", lambda: {"ok": 2})
    app = FastAPI()
    register_routers(app, (
        router_registration("first", first), router_registration("second", second),
    ))
    assert app.state.registered_router_groups == ["first", "second"]
    paths = [route.path for route in app.routes]
    assert paths.index("/first") < paths.index("/second")


def test_typed_router_registry_rejects_duplicate_names():
    app, router = FastAPI(), APIRouter()
    with pytest.raises(ValueError, match="duplicate_router_registration_name"):
        register_routers(app, (
            router_registration("same", router), router_registration("same", router),
        ))
