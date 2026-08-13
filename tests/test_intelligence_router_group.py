from fastapi import FastAPI

from src.app.bootstrap.intelligence_router_group import register_intelligence_router_group


def test_intelligence_router_group_registers_expected_surfaces():
    app = FastAPI()
    registered = register_intelligence_router_group(app)
    paths = {route.path for route in app.routes}
    assert "session_events" in registered
    assert "hippograph" in registered
    assert "/api/v1/hippograph/journey" in paths
    assert app.state.intelligence_router_group == registered
