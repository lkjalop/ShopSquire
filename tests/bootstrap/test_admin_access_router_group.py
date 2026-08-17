from fastapi import FastAPI

from src.app.bootstrap.admin_access_router_group import register_admin_access_router_group


def test_admin_access_router_group_records_optional_registration_truth():
    app = FastAPI()
    registered = register_admin_access_router_group(app)
    projection = app.state.admin_access_router_group
    assert registered[0] == "admin"
    assert tuple(projection["registered"]) == registered
    assert isinstance(projection["optional_failures"], dict)
    assert any(getattr(route, "path", "").startswith("/api/v1/admin") for route in app.routes)
